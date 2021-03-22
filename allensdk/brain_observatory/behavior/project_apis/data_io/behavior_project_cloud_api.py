import pandas as pd
from typing import Iterable, Union, Dict, List
from pathlib import Path
import logging
import ast
import semver

from allensdk.brain_observatory.behavior.project_apis.abcs import (
    BehaviorProjectBase)
from allensdk.brain_observatory.behavior.behavior_session import (
    BehaviorSession)
from allensdk.brain_observatory.behavior.behavior_ophys_experiment import (
    BehaviorOphysExperiment)
from allensdk.api.cloud_cache.cloud_cache import S3CloudCache
from allensdk import __version__ as sdk_version


# [min inclusive, max exclusive)
COMPATIBILITY = {
        "pipeline_versions": {
            "2.9.0": {"AllenSDK": ["2.9.0", "3.0.0"]},
            "2.10.0": {"AllenSDK": ["2.9.0", "3.0.0"]}}}


class BehaviorCloudCacheVersionException(Exception):
    pass


def version_check(pipeline_versions: List[Dict[str, str]],
                  sdk_version: str = sdk_version,
                  compatibility: Dict[str, Dict] = COMPATIBILITY):
    """given a pipeline_versions list (from manifest) determine
    the pipeline version of AllenSDK used to write the data. Lookup
    the compatibility limits, and check the the running version of
    AllenSDK meets those limits.

    Parameters
    ----------
    pipeline_versions: List[Dict[str, str]]:
        each element has keys name, version, (and comment - not used here)
    sdk_version: str
        typically the current return value for allensdk.__version__
    compatibility_dict: Dict
        keys (under 'pipeline_versions' key) are specific version numbers to
        match a pipeline version for AllenSDK from the manifest. values
        specify the min (inclusive) and max (exclusive) limits for
        interoperability

    Raises
    ------
    BehaviorCloudCacheVersionException

    """
    pipeline_version = [i for i in pipeline_versions
                        if "AllenSDK" == i["name"]]
    if len(pipeline_version) != 1:
        raise BehaviorCloudCacheVersionException(
                "expected to find 1 and only 1 entry for `AllenSDK` "
                "in the manifest.data_pipeline metadata. "
                f"found {len(pipeline_version)}")
    pipeline_version = pipeline_version[0]["version"]
    if pipeline_version not in compatibility["pipeline_versions"]:
        raise BehaviorCloudCacheVersionException(
                f"no version compatibility listed for {pipeline_version}")
    version_limits = compatibility["pipeline_versions"][pipeline_version]
    smin = semver.VersionInfo.parse(version_limits["AllenSDK"][0])
    smax = semver.VersionInfo.parse(version_limits["AllenSDK"][1])
    if (sdk_version < smin) | (sdk_version >= smax):
        raise BehaviorCloudCacheVersionException(
            f"""
            The version of the visual-behavior-ophys data files (specified
            in path_to_users_current_release_manifest) requires that your
            AllenSDK version be >={smin} and <{smax}.
            Your version of AllenSDK is: {sdk_version}.
            If you want to use the specified manifest to retrieve data, please
            upgrade or downgrade AllenSDK to the range specified.
            If you just want to get the latest version of visual-behavior-ophys
            data please upgrade to the latest AllenSDK version and try this
            process again.""")


def literal_col_eval(df: pd.DataFrame,
                     columns: List[str] = ["ophys_experiment_id",
                                           "ophys_container_id",
                                           "driver_line"]) -> pd.DataFrame:
    def converter(x):
        if isinstance(x, str):
            x = ast.literal_eval(x)
        return x

    for column in columns:
        if column in df.columns:
            df.loc[df[column].notnull(), column] = \
                df[column][df[column].notnull()].apply(converter)
    return df


class BehaviorProjectCloudApi(BehaviorProjectBase):
    """API for downloading data released on S3 and returning tables.

    Parameters
    ----------
    cache: S3CloudCache
        an instantiated S3CloudCache object, which has already run
        `self.load_manifest()` which populates the columns:
          - metadata_file_names
          - file_id_column
    skip_version_check: bool
        whether to skip the version checking of pipeline SDK version
        vs. running SDK version, which may raise Exceptions. (default=False)

    """
    def __init__(self, cache: S3CloudCache, skip_version_check: bool = False):
        expected_metadata = set(["behavior_session_table",
                                 "ophys_session_table",
                                 "ophys_experiment_table"])
        self.cache = cache
        if cache._manifest.metadata_file_names is None:
            raise RuntimeError("S3CloudCache object has no metadata "
                               "file names. BehaviorProjectCloudApi "
                               "expects a S3CloudCache passed which "
                               "has already run load_manifest()")
        cache_metadata = set(cache._manifest.metadata_file_names)
        if cache_metadata != expected_metadata:
            raise RuntimeError("expected S3CloudCache object to have "
                               f"metadata file names: {expected_metadata} "
                               f"but it has {cache_metadata}")
        if not skip_version_check:
            version_check(self.cache._manifest._data_pipeline)
        self.logger = logging.getLogger("BehaviorProjectCloudApi")
        self._get_session_table()
        self._get_behavior_only_session_table()
        self._get_experiment_table()

    @staticmethod
    def from_s3_cache(cache_dir: Union[str, Path],
                      bucket_name: str,
                      project_name: str) -> "BehaviorProjectCloudApi":
        """instantiates this object with a connection to an s3 bucket and/or
        a local cache related to that bucket.

        Parameters
        ----------
        cache_dir: str or pathlib.Path
            Path to the directory where data will be stored on the local system

        bucket_name: str
            for example, if bucket URI is 's3://mybucket' this value should be
            'mybucket'

        project_name: str
            the name of the project this cache is supposed to access. This
            project name is the first part of the prefix of the release data
            objects. I.e. s3://<bucket_name>/<project_name>/<object tree>

        Returns
        -------
        BehaviorProjectCloudApi instance

        """
        cache = S3CloudCache(cache_dir, bucket_name, project_name)
        cache.load_latest_manifest()
        return BehaviorProjectCloudApi(cache)

    def get_behavior_session(
            self, behavior_session_id: int) -> BehaviorSession:
        """get a BehaviorSession by specifying behavior_session_id

        Parameters
        ----------
        behavior_session_id: int
            the id of the behavior_session

        Returns
        -------
        BehaviorSession

        Notes
        -----
        entries in the _behavior_only_session_table represent
        (1) ophys_sessions which have a many-to-one mapping between nwb files
        and behavior sessions. (file_id is NaN)
        AND
        (2) behavior only sessions, which have a one-to-one mapping with
        nwb files. (file_id is not Nan)
        In the case of (1) this method returns an object which is just behavior
        data which is shared by all experiments in 1 session. This is extracted
        from the nwb file for the first-listed ophys_experiment.

        """
        row = self._behavior_only_session_table.query(
                f"behavior_session_id=={behavior_session_id}")
        if row.shape[0] != 1:
            raise RuntimeError("The behavior_only_session_table should have "
                               "1 and only 1 entry for a given "
                               "behavior_session_id. For "
                               f"{behavior_session_id} "
                               f" there are {row.shape[0]} entries.")
        row = row.squeeze()
        has_file_id = not pd.isna(row[self.cache.file_id_column])
        if not has_file_id:
            oeid = row.ophys_experiment_id[0]
            row = self._experiment_table.query(
                f"ophys_experiment_id=={oeid}").squeeze()
        data_path = self.cache.download_data(
                str(int(row[self.cache.file_id_column])))
        return BehaviorSession.from_nwb_path(str(data_path))

    def get_behavior_ophys_experiment(self, ophys_experiment_id: int
                                      ) -> BehaviorOphysExperiment:
        """get a BehaviorOphysExperiment by specifying ophys_experiment_id

        Parameters
        ----------
        ophys_experiment_id: int
            the id of the ophys_experiment

        Returns
        -------
        BehaviorOphysExperiment

        """
        row = self._experiment_table.query(
                f"ophys_experiment_id=={ophys_experiment_id}")
        if row.shape[0] != 1:
            raise RuntimeError("The behavior_ophys_experiment_table should "
                               "have 1 and only 1 entry for a given "
                               f"ophys_experiment_id. For "
                               f"{ophys_experiment_id} "
                               f" there are {row.shape[0]} entries.")
        row = row.squeeze()
        data_path = self.cache.download_data(
                str(int(row[self.cache.file_id_column])))
        return BehaviorOphysExperiment.from_nwb_path(str(data_path))

    def _get_session_table(self) -> pd.DataFrame:
        session_table_path = self.cache.download_metadata(
                "ophys_session_table")
        self._session_table = literal_col_eval(pd.read_csv(session_table_path))

    def get_session_table(self) -> pd.DataFrame:
        """Return a pd.Dataframe table summarizing ophys_sessions
        and associated metadata.

        Notes
        -----
        - Each entry in this table represents the metadata of an ophys_session.
        Link to nwb-hosted files in the cache is had via the
        'ophys_experiment_id' column (can be a list)
        and experiment_table
        """
        return self._session_table

    def _get_behavior_only_session_table(self):
        session_table_path = self.cache.download_metadata(
                "behavior_session_table")
        self._behavior_only_session_table = literal_col_eval(
                pd.read_csv(session_table_path))

    def get_behavior_only_session_table(self) -> pd.DataFrame:
        """Return a pd.Dataframe table with both behavior-only
        (BehaviorSession) and with-ophys (BehaviorOphysExperiment)
        sessions as entries.

        Notes
        -----
        - In the first case, provides a critical mapping of
        behavior_session_id to file_id, which the cache uses to find the
        nwb path in cache.
        - In the second case, provides a critical mapping of
        behavior_session_id to a list of ophys_experiment_id(s)
        which can be used to find file_id mappings in experiment_table
        see method get_behavior_session()
        - the BehaviorProjectCache calls this method through a method called
        get_behavior_session_table. The name of this method is a legacy shared
        with the behavior_project_lims_api and should be made consistent with
        the BehaviorProjectCache calling method.
        """
        return self._behavior_only_session_table

    def _get_experiment_table(self):
        experiment_table_path = self.cache.download_metadata(
                "ophys_experiment_table")
        self._experiment_table = literal_col_eval(
                pd.read_csv(experiment_table_path))

    def get_experiment_table(self):
        """returns a pd.DataFrame where each entry has a 1-to-1
        relation with an ophys experiment (i.e. imaging plane)

        Notes
        -----
        - the file_id column allows the underlying cache to link
        this table to a cache-hosted NWB file. There is a 1-to-1
        relation between nwb files and ophy experiments. See method
        get_behavior_ophys_experiment()
        """
        return self._experiment_table

    def get_natural_movie_template(self, number: int) -> Iterable[bytes]:
        """ Download a template for the natural movie stimulus. This is the
        actual movie that was shown during the recording session.
        :param number: identifier for this scene
        :type number: int
        :returns: An iterable yielding an npy file as bytes
        """
        raise NotImplementedError()

    def get_natural_scene_template(self, number: int) -> Iterable[bytes]:
        """Download a template for the natural scene stimulus. This is the
        actual image that was shown during the recording session.
        :param number: idenfifier for this movie (note that this is an int,
            so to get the template for natural_movie_three should pass 3)
        :type number: int
        :returns: iterable yielding a tiff file as bytes
        """
        raise NotImplementedError()
