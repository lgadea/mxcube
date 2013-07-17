import os
import logging
import ShapeHistory as shape_history
import queue_item
import copy
import widget_utils
import math
import queue_model_objects_v1 as queue_model_objects

from qt import *
from widgets.data_path_widget import DataPathWidget
from widgets.data_path_widget_vertical_layout import\
    DataPathWidgetVerticalLayout
from widgets.acquisition_widget import AcquisitionWidget
from widgets.acquisition_widget_vertical_layout \
    import AcquisitionWidgetVerticalLayout
from widgets.widget_utils import DataModelInputBinder
from create_task_base import CreateTaskBase

from widgets.processing_widget import ProcessingWidget


class CreateDiscreteWidget(CreateTaskBase):
    def __init__(self,parent = None,name = None, fl = 0):
        CreateTaskBase.__init__(self, parent, name, fl, 'Discrete')

        if not name:
            self.setName("create_discrete_widget")

        #
        # Data attributes
        #
        self.previous_energy = None
        self.init_models()

        #
        # Layout
        #
        v_layout = QVBoxLayout(self, 2, 5, "v_layout")
        self._acq_gbox = QVGroupBox('Acquisition', self, 'acq_gbox')
        self._acq_widget = AcquisitionWidget(self._acq_gbox, 
                                            "acquisition_widget",
                                            layout = AcquisitionWidgetVerticalLayout,
                                            acq_params =  self._acquisition_parameters,
                                            path_template = self._path_template)


        self._data_path_gbox = QVGroupBox('Data location', self, 'data_path_gbox')
        self._data_path_widget = DataPathWidget(self._data_path_gbox,
                                                'create_dc_path_widget',
                                                data_model = self._path_template,
                                                layout = DataPathWidgetVerticalLayout)

        self._processing_gbox = QVGroupBox('Processing', self, 
                                           'processing_gbox')

        self._processing_widget = ProcessingWidget(self._processing_gbox,
                                                   data_model = self._processing_parameters)
        
        v_layout.addWidget(self._acq_gbox)
        v_layout.addWidget(self._data_path_gbox)
        v_layout.addWidget(self._processing_gbox)
        v_layout.addStretch()


        self.connect(self._acq_widget, PYSIGNAL('mad_energy_selected'),
                     self.mad_energy_selected)


        self.connect(self._data_path_widget.data_path_widget_layout.prefix_ledit, 
                     SIGNAL("textChanged(const QString &)"), 
                     self._prefix_ledit_change)


        self.connect(self._data_path_widget.data_path_widget_layout.run_number_ledit,
                     SIGNAL("textChanged(const QString &)"), 
                     self._run_number_ledit_change)


    def init_models(self):
        self._energy_scan_result = queue_model_objects.EnergyScanResult()
        self._processing_parameters = queue_model_objects.ProcessingParameters()

        if self._bl_config_hwobj is not None:
            self._acquisition_parameters = self._bl_config_hwobj.\
                                           get_default_acquisition_parameters()

            self._path_template =  self._bl_config_hwobj.\
                                  get_default_path_template()    
        else:
            self._acquisition_parameters = queue_model_objects.AcquisitionParameters()
            self._path_template = queue_model_objects.PathTemplate()
        
        if self._beamline_setup_hwobj is not None:
            try:
                transmission = self._beamline_setup_hwobj.transmission_hwobj.getAttFactor()
                transmission = round(float(transmission), 1)
            except AttributeError:
                transmission = 0

            try:
                resolution = self._beamline_setup_hwobj.resolution_hwobj.getPosition()
                resolution = round(float(resolution), 4)
            except AttributeError:
                resolution = 0

            try:
                energy = self._beamline_setup_hwobj.energy_hwobj.getCurrentEnergy()
                energy = round(float(energy), 2)
            except AttributeError:
                energy = 0

            self._acquisition_parameters.resolution = resolution
            self._acquisition_parameters.energy = energy
            self._acquisition_parameters.transmission = transmission

        if self._bl_config_hwobj:
            has_shutter_less = self._bl_config_hwobj.detector_has_shutterless()
            self._acquisition_parameters.shutterless = has_shutter_less

    def _prefix_ledit_change(self, new_value):
        item = self._current_selected_item
        
        if isinstance(item, queue_item.DataCollectionQueueItem):
            prefix = self._path_template.get_prefix()
            item.get_model().set_name(prefix)
            item.setText(0, item.get_model().get_name())
        

    def _run_number_ledit_change(self, new_value):
        item = self._current_selected_item
        
        if isinstance(item, queue_item.DataCollectionQueueItem):
            if str(new_value).isdigit():
                item.get_model().set_number(int(new_value))
                item.setText(0, item.get_model().get_name())


    def set_tunable_energy(self, state):
        self._acq_widget.set_tunable_energy(state)


    def update_processing_parameters(self, crystal):
        self._processing_parameters.space_group = crystal.space_group
        self._processing_parameters.cell_a = crystal.cell_a
        self._processing_parameters.cell_alpha = crystal.cell_alpha
        self._processing_parameters.cell_b = crystal.cell_b
        self._processing_parameters.cell_beta = crystal.cell_beta
        self._processing_parameters.cell_c = crystal.cell_c
        self._processing_parameters.cell_gamma = crystal.cell_gamma
        self._processing_widget.update_data_model(self._processing_parameters)


    def select_shape_with_cpos(self, cpos):
        self._shape_history._drawing_event.de_select_all()

        for shape in self._shape_history.get_shapes():
            if len(shape.get_centred_positions()) == 1:
                if shape.get_centred_positions()[0] is cpos:
                    self._shape_history._drawing_event.set_selected(shape)


    def _selection_changed(self, tree_item):
        if isinstance(tree_item, queue_item.SampleQueueItem) or \
               isinstance(tree_item, queue_item.DataCollectionGroupQueueItem):

            self.init_models()
            sample_data_model = self.get_sample_item().get_model()
            self.update_processing_parameters(sample_data_model.crystals[0])
            self._acq_widget.set_energies(sample_data_model.crystals[0].energy_scan_result)
           
            (data_directory, proc_directory) = self.get_default_directory()
                
            self._path_template.directory = data_directory
            self._path_template.process_directory = proc_directory
            self._path_template.base_prefix = self.get_default_prefix(sample_data_model)
            self._path_template.run_number = self._tree_brick.queue_model_hwobj.\
                                             get_run_number(self._path_template)
        
        elif isinstance(tree_item, queue_item.DataCollectionQueueItem):
            data_collection = tree_item.get_model()
            self._path_template = data_collection.acquisitions[0].path_template
            self._acquisition_parameters = data_collection.acquisitions[0].\
                                           acquisition_parameters

            if len(data_collection.acquisitions) == 1:
                self.select_shape_with_cpos(self._acquisition_parameters.centred_position)
            
            self._energy_scan_result = queue_model_objects.EnergyScanResult()
            self._processing_parameters = data_collection.processing_parameters
            self._energy_scan_result = data_collection.crystal.energy_scan_result
            self._acq_widget.set_energies(self._energy_scan_result)
            
        self._processing_widget.update_data_model(self._processing_parameters)
        self._acq_widget.update_data_model(self._acquisition_parameters,
                                           self._path_template)
        self._data_path_widget.update_data_model(self._path_template)
        

    # Called by the owning widget (task_toolbox_widget) to create
    # a collection. When a data collection group is selected.
    def _create_task(self, parent_task_node, sample):       
        selected_positions = []
        tasks = []

        if not self._selected_positions:
            cpos = None

            if self._tree_brick.diffractometer_hwobj:
                pos_dict = self._tree_brick.diffractometer_hwobj.getPositions()
                cpos = queue_model_objects.CentredPosition(pos_dict)

            logging.getLogger("user_level_log").\
                info("No centred position(s) was selected " + str(cpos) + \
                     " (current position) will be used.")

            selected_shapes = [shape_history.Point(None, cpos, None)]
        else:
            selected_shapes = self._shape_history.selected_shapes

        invalid = False
                
        if invalid:
            msg = "There are one or more invalid values among the" +\
                " collection parameters."

            logging.getLogger("user_level_log").\
                warning(msg)
            
        for shape in selected_shapes:
            snapshot = None
            
            if isinstance(shape, shape_history.Point):
                sc = None
                
                if not shape.get_drawing():
                    sc = queue_model_objects.SampleCentring()
                    sc.set_name('sample-centring')
                    tasks.append(sc)

                if shape.qub_point is not None:
                    snapshot = self._shape_history.get_snapshot([shape.qub_point])
                else:
                    snapshot = self._shape_history.get_snapshot([])

                # Acquisition for start position
                acq = queue_model_objects.Acquisition()
                acq.acquisition_parameters = \
                    copy.deepcopy(self._acquisition_parameters)
                acq.acquisition_parameters.collect_agent = \
                    queue_model_objects.COLLECTION_ORIGIN.MXCUBE
                acq.acquisition_parameters.\
                    centred_position = shape.get_centred_positions()[0]
                acq.path_template = copy.deepcopy(self._path_template)
                acq.acquisition_parameters.centred_position.\
                    snapshot_image = snapshot

                processing_parameters = copy.deepcopy(self._processing_parameters)
                
                dc = queue_model_objects.DataCollection([acq],
                                                        sample.crystals[0],
                                                        processing_parameters)

                dc.set_name(acq.path_template.get_prefix())
                dc.set_number(self._path_template.run_number)
                #self._path_template.run_number += 1

                dc.experiment_type = queue_model_objects.EXPERIMENT_TYPE.NATIVE

                if sc:
                    sc.set_task(dc)
                
                tasks.append(dc)

        return tasks
    
        