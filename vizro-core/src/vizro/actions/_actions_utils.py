"""Contains utilities for the implementation of action functions."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, TypedDict, Union

import pandas as pd

from vizro._constants import ALL_OPTION, NONE_OPTION
from vizro.managers import data_manager, model_manager
from vizro.managers._model_manager import ModelID
from vizro.models.types import MultiValueType, SelectorType, SingleValueType

if TYPE_CHECKING:
    from vizro.models import Action

ValidatedNoneValueType = Union[SingleValueType, MultiValueType, None, List[None]]


class CallbackTriggerDict(TypedDict):  # shortened as 'ctd'
    id: ModelID  # the component ID. If it`s a pattern matching ID, it will be a dict.
    property: Literal["clickData", "value", "n_clicks", "active_cell"]  #  the component property used in the callback.
    value: Optional[Any]  # the value of the component property at the time the callback was fired.
    str_id: str  # for pattern matching IDs, it`s the stringified dict ID with no white spaces.
    triggered: bool  #  a boolean indicating whether this input triggered the callback.


# Utility functions for helper functions used in pre-defined actions ----
def _get_component_actions(component) -> List[Action]:
    return (
        [action for actions_chain in component.actions for action in actions_chain.actions]
        if hasattr(component, "actions")
        else []
    )


def _validate_selector_value_NONE(value: Union[SingleValueType, MultiValueType]) -> ValidatedNoneValueType:
    if value == NONE_OPTION:
        return None
    elif isinstance(value, list):
        return [i for i in value if i != NONE_OPTION] or [None]  # type: ignore[list-item, return-value]
    return value


def _apply_filters(
    data_frame: pd.DataFrame,
    ctds_filters: List[CallbackTriggerDict],
    target: str,
) -> pd.DataFrame:
    for ctd in ctds_filters:
        selector_value = ctd["value"]
        selector_value = selector_value if isinstance(selector_value, list) else [selector_value]
        selector_actions = _get_component_actions(model_manager[ctd["id"]])

        for action in selector_actions:
            if target not in action.function["targets"] or ALL_OPTION in selector_value:
                continue

            _filter_function = action.function["filter_function"]
            _filter_column = action.function["filter_column"]
            _filter_value = selector_value
            data_frame = data_frame[_filter_function(data_frame[_filter_column], _filter_value)]

    return data_frame


def _apply_filter_interaction(
    data_frame: pd.DataFrame,
    ctds_filter_interaction: List[CallbackTriggerDict],
    target: str,
) -> pd.DataFrame:
    for ctd in ctds_filter_interaction:
        if not ctd["value"]:
            continue

        source_chart_id = ctd["id"]
        source_chart_actions = _get_component_actions(model_manager[source_chart_id])

        try:
            custom_data_columns = model_manager[source_chart_id]["custom_data"]  # type: ignore[index]
        except KeyError as exc:
            raise KeyError(f"No `custom_data` argument found for source chart with id {source_chart_id}.") from exc

        customdata = ctd["value"]["points"][0]["customdata"]

        for action in source_chart_actions:
            if target not in action.function["targets"]:
                continue

            for custom_data_idx, column in enumerate(custom_data_columns):
                data_frame = data_frame[data_frame[column].isin([customdata[custom_data_idx]])]
    return data_frame


def _create_target_arg_mapping(dot_separated_strings: List[str]) -> Dict[str, List[str]]:
    results = defaultdict(list)
    for string in dot_separated_strings:
        if "." not in string:
            raise ValueError(f"Provided string {string} must contain a '.'")
        component, arg = string.split(".", 1)
        results[component].append(arg)
    return results


def _update_nested_graph_properties(graph_config: Dict[str, Any], dot_separated_string: str, value: Any):
    keys = dot_separated_string.split(".")
    current_property = graph_config
    for key in keys[:-1]:
        current_property = current_property[key]
    current_property[keys[-1]] = value
    return graph_config


def _get_parametrized_config(
    targets: List[ModelID], parameters: List[CallbackTriggerDict]
) -> Dict[ModelID, Dict[str, Any]]:
    parameterized_config = {}
    for target in targets:
        # TODO - avoid calling _captured_callable. Once we have done this we can remove _arguments from
        #  CapturedCallable entirely.
        graph_config = deepcopy(model_manager[target].figure._arguments)  # type: ignore[attr-defined]
        if "data_frame" in graph_config:
            graph_config.pop("data_frame")

        for ctd in parameters:
            selector_value = ctd[
                "value"
            ]  # TODO: needs to be refactored so that it is independent of implementation details
            if hasattr(selector_value, "__iter__") and ALL_OPTION in selector_value:  # type: ignore[operator]
                selector: SelectorType = model_manager[ctd["id"]]
                selector_value = selector.options
            selector_value = _validate_selector_value_NONE(selector_value)
            selector_actions = _get_component_actions(model_manager[ctd["id"]])

            for action in selector_actions:
                action_targets = _create_target_arg_mapping(action.function["targets"])

                if target not in action_targets:
                    continue

                for action_targets_arg in action_targets[target]:
                    graph_config = _update_nested_graph_properties(
                        graph_config=graph_config, dot_separated_string=action_targets_arg, value=selector_value
                    )

        parameterized_config[target] = graph_config

    return parameterized_config


# Helper functions used in pre-defined actions ----
def _get_filtered_data(
    targets: List[ModelID],
    ctds_filters: List[CallbackTriggerDict],
    ctds_filter_interaction: List[CallbackTriggerDict],
) -> Dict[ModelID, pd.DataFrame]:
    filtered_data = {}
    for target in targets:
        data_frame = data_manager._get_component_data(target)

        data_frame = _apply_filters(
            data_frame=data_frame,
            ctds_filters=ctds_filters,
            target=target,
        )
        data_frame = _apply_filter_interaction(
            data_frame=data_frame,
            ctds_filter_interaction=ctds_filter_interaction,
            target=target,
        )

        filtered_data[target] = data_frame

    return filtered_data


def _get_modified_page_charts(
    ctds_filter: List[CallbackTriggerDict],
    ctds_filter_interaction: List[CallbackTriggerDict],
    ctds_parameters: List[CallbackTriggerDict],
    ctd_theme: CallbackTriggerDict,
    targets: Optional[List[ModelID]] = None,
) -> Dict[ModelID, Any]:
    if not targets:
        targets = []
    filtered_data = _get_filtered_data(
        targets=targets,
        ctds_filters=ctds_filter,
        ctds_filter_interaction=ctds_filter_interaction,
    )

    parameterized_config = _get_parametrized_config(
        targets=targets,
        parameters=ctds_parameters,
    )

    outputs = {}
    for target in targets:
        outputs[target] = model_manager[target](  # type: ignore[operator]
            data_frame=filtered_data[target], **parameterized_config[target]
        )
        if hasattr(outputs[target], "update_layout"):
            outputs[target].update_layout(template="vizro_dark" if ctd_theme["value"] else "vizro_light")

    return outputs
