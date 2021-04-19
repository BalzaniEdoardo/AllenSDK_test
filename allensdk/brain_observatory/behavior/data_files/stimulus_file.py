import json
from typing import Dict, Union
from pathlib import Path

import pandas as pd

from allensdk.internal.api import PostgresQueryMixin
from allensdk.internal.core.lims_utilities import safe_system_path
from allensdk.brain_observatory.behavior.data_files import DataFile

class StimulusFile(DataFile):

    def __init__(self, filepath: Union[str, Path]):
        super().__init__(filepath=filepath)

    @classmethod
    def from_json(cls, dict_repr: dict) -> "StimulusFile":
        filepath = dict_repr["behavior_stimulus_file"]
        return cls(filepath=filepath)

    def to_json(self) -> Dict[str, str]:
        return {"behavior_stimulus_file": str(self.filepath)}

    @classmethod
    def from_lims(
        cls, db: PostgresQueryMixin,
        behavior_session_id: Union[int, str]
    ) -> "StimulusFile":
        # Query returns the path to the StimulusPickle file for the given
        # behavior session
        query = f"""
            SELECT
                wkf.storage_directory || wkf.filename AS stim_file
            FROM
                well_known_files wkf
            WHERE
                wkf.attachable_id = {behavior_session_id}
                AND wkf.attachable_type = 'BehaviorSession'
                AND wkf.well_known_file_type_id IN (
                    SELECT id
                    FROM well_known_file_types
                    WHERE name = 'StimulusPickle');
        """
        filepath = db.fetchone(query, strict=True)
        return cls(filepath=filepath)

    @staticmethod
    def load_data(filepath: Union[str, Path]) -> dict:
        filepath = safe_system_path(file_name=filepath)
        return pd.read_pickle(filepath)
