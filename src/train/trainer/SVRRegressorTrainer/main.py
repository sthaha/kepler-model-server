import os
import sys

from sklearn.svm import SVR

trainer_path = os.path.join(os.path.dirname(__file__), "..")
sys.path.append(trainer_path)

common_node_type = 1
from trainer.scikit import ScikitTrainer


class SVRRegressorTrainer(ScikitTrainer):
    def __init__(self, energy_components, feature_group, energy_source, node_level, pipeline_name):
        super(SVRRegressorTrainer, self).__init__(
            energy_components, feature_group, energy_source, node_level, pipeline_name=pipeline_name
        )
        self.fe_files = []

    def init_model(self):
        return SVR(C=1.0, epsilon=0.2)
