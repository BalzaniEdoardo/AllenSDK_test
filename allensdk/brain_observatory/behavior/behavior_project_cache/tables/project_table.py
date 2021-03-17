import re
from abc import abstractmethod, ABC
from typing import Optional, List

import pandas as pd

from allensdk.brain_observatory.behavior.metadata.behavior_metadata import \
    BehaviorMetadata


class ProjectTable(ABC):
    """Class for storing and manipulating project-level data"""
    def __init__(self, df: pd.DataFrame,
                 suppress: Optional[List[str]] = None):
        """
        Parameters
        ----------
        df
            The project-level data
        suppress
            columns to drop from table

        """
        self._df = df
        self._suppress = suppress

        self.postprocess()

    @property
    def table(self):
        return self._df

    def postprocess_base(self):
        """Postprocessing to apply to all project-level data"""
        # Make sure the index is not duplicated (it is rare)
        self._df = self._df[~self._df.index.duplicated()].copy()

        self._df['reporter_line'] = self._df['reporter_line'].apply(
            BehaviorMetadata.parse_reporter_line)
        self._df['cre_line'] = self._df['full_genotype'].apply(
            BehaviorMetadata.parse_cre_line)
        self._df['indicator'] = self._df['reporter_line'].apply(
            BehaviorMetadata.parse_indicator)

        self.__add_session_number()

    def postprocess(self):
        """Postprocess loop"""
        self.postprocess_base()
        self.postprocess_additional()

        if self._suppress:
            self._df.drop(columns=self._suppress, inplace=True,
                          errors="ignore")

    @abstractmethod
    def postprocess_additional(self):
        """Additional postprocessing should be overridden by subclassess"""
        raise NotImplementedError()

    def __add_session_number(self):
        """Parses session number from session type and and adds to dataframe"""
        def parse_session_number(session_type: str):
            """Parse the session number from session type"""
            match = re.match(r'OPHYS_(?P<session_number>\d+)',
                             session_type)
            if match is None:
                return None
            return int(match.group('session_number'))

        session_type = self._df['session_type']
        session_type = session_type[session_type.notnull()]

        self._df.loc[session_type.index, 'session_number'] = \
            session_type.apply(parse_session_number)
