import pandas as pd
import numpy as np
from pynwb import NWBFile
from pynwb.ophys import DfOverF

from allensdk.brain_observatory.behavior.data_files.dff_file import DFFFile
from allensdk.brain_observatory.behavior.data_objects import DataObject
from allensdk.brain_observatory.behavior.data_objects.base \
    .readable_interfaces import \
    DataFileReadableInterface, NwbReadableInterface
from allensdk.brain_observatory.behavior.data_objects.base\
    .writable_interfaces import \
    NwbWritableInterface
from allensdk.brain_observatory.behavior.data_objects.timestamps\
    .ophys_timestamps import \
    OphysTimestamps


class DFF_traces(DataObject, DataFileReadableInterface, NwbReadableInterface,
                 NwbWritableInterface):
    def __init__(self, traces: pd.DataFrame):
        super().__init__(name='dff_traces', value=traces)

    def to_nwb(self, nwbfile: NWBFile,
               ophys_timestamps: OphysTimestamps) -> NWBFile:
        dff_traces = self.value[['dff']]

        ophys_module = nwbfile.processing['ophys']
        # trace data in the form of rois x timepoints
        trace_data = np.array([dff_traces.loc[cell_roi_id].dff
                               for cell_roi_id in dff_traces.index.values])

        cell_specimen_table = nwbfile.processing['ophys'].data_interfaces[
            'image_segmentation'].plane_segmentations[
            'cell_specimen_table']  # noqa: E501
        roi_table_region = cell_specimen_table.create_roi_table_region(
            description="segmented cells labeled by cell_specimen_id",
            region=slice(len(dff_traces)))

        # Create/Add dff modules and interfaces:
        assert dff_traces.index.name == 'cell_roi_id'
        dff_interface = DfOverF(name='dff')
        ophys_module.add_data_interface(dff_interface)

        dff_interface.create_roi_response_series(
            name='traces',
            data=trace_data.T,  # Should be stored as timepoints x rois
            unit='NA',
            rois=roi_table_region,
            timestamps=ophys_timestamps.value)

        return nwbfile

    @classmethod
    def from_nwb(cls, nwbfile: NWBFile) -> "DFF_traces":
        dff_nwb = nwbfile.processing[
            'ophys'].data_interfaces['dff'].roi_response_series['traces']
        # dff traces stored as timepoints x rois in NWB
        # We want rois x timepoints, hence the transpose
        dff_traces = dff_nwb.data[:].T

        df = pd.DataFrame({'dff': dff_traces.tolist()},
                          index=pd.Index(data=dff_nwb.rois.table.id[:],
                                         name='cell_roi_id'))
        return DFF_traces(traces=df)

    @classmethod
    def from_data_file(cls, dff_file: DFFFile) -> "DFF_traces":
        dff_traces = dff_file.data
        return DFF_traces(traces=dff_traces)
