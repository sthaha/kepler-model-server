import os
import sys

cur_path = os.path.join(os.path.dirname(__file__), ".")
sys.path.append(cur_path)

model_path = os.path.join(os.path.dirname(__file__), "model")
sys.path.append(model_path)

from estimate_common import compute_error
from model import (
    default_idle_predicted_col_func,
    default_predicted_col_func,
    get_background_containers,
    get_dynamic_power_colname,
    get_label_power_colname,
    get_predicted_background_power_colname,
    get_predicted_dynamic_background_power_colname,
    get_predicted_dynamic_power_colname,
    get_predicted_power_colname,
    get_reconstructed_power_colname,
    load_model,
)
