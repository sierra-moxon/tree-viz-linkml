# Thanks https://towardsdatascience.com/create-and-deploy-a-simple-web-application-with-flask-and-heroku-103d867298eb
import argparse
from collections import defaultdict
from typing import Tuple, List

import requests
import yaml
from flask import Flask, render_template

app = Flask(__name__)


def convert_predicate_to_trapi_format(english_predicate: str) -> str:
    # Converts a string like "treated by" to "treated_by"
    return english_predicate.replace(' ', '_')


def convert_category_to_trapi_format(english_category: str) -> str:
    # Converts a string like "named thing" to "NamedThing"
    return "".join([f"{word[0].upper()}{word[1:]}" for word in english_category.split(" ")])


def get_tree_node_recursive(root_node: dict, parent_to_child_map: dict):
    root_name = root_node["name"]
    children_predicates = parent_to_child_map.get(root_name, [])
    if children_predicates:
        children = []
        for child_predicate in children_predicates:
            child_node = {"name": child_predicate, "parent": root_name}
            child_node = get_tree_node_recursive(child_node, parent_to_child_map)
            children.append(child_node)
        root_node["children"] = sorted(children, key=lambda x: x["name"])
    return root_node


def get_biolink_data(biolink_version: str) -> requests.Response:
    response = requests.get(f"https://raw.githubusercontent.com/biolink/biolink-model/"
                            f"{biolink_version if biolink_version else 'master'}/biolink-model.yaml",
                            timeout=10)
    if response.status_code != 200:  # Sometimes Biolink's tags start with 'v', so try that
        response = requests.get(f"https://raw.githubusercontent.com/biolink/biolink-model/v{biolink_version}/biolink-model.yaml",
                                timeout=10)
    return response


def load_predicate_tree_data(biolink_version: str) -> Tuple[List[dict], str]:
    # Grab Biolink yaml file and load into dictionary tree structures
    response = get_biolink_data(biolink_version)
    if response.status_code == 200:
        # Build predicates tree
        biolink_model = yaml.safe_load(response.text)
        parent_to_child_dict = defaultdict(set)
        for slot_name_english, info in biolink_model["slots"].items():
            slot_name = convert_predicate_to_trapi_format(slot_name_english)
            parent_name_english = info.get("is_a")
            if parent_name_english:
                parent_name = convert_predicate_to_trapi_format(parent_name_english)
                parent_to_child_dict[parent_name].add(slot_name)
        root_node = {"name": "related_to"}
        predicate_tree = get_tree_node_recursive(root_node, parent_to_child_dict)

        biolink_version = biolink_model["version"]
        return [predicate_tree], biolink_version
    else:
        return [], ""


def load_category_tree_data(biolink_version: str) -> Tuple[List[dict], str]:
    # Grab Biolink yaml file and load into dictionary tree structures
    response = get_biolink_data(biolink_version)
    if response.status_code == 200:
        # Build categories tree
        biolink_model = yaml.safe_load(response.text)
        parent_to_child_dict = defaultdict(set)
        for slot_name_english, info in biolink_model["classes"].items():
            slot_name = convert_category_to_trapi_format(slot_name_english)
            parent_name_english = info.get("is_a")
            if parent_name_english:
                parent_name = convert_category_to_trapi_format(parent_name_english)
                parent_to_child_dict[parent_name].add(slot_name)

        root_node = {"name": "NamedThing", "parent": None}
        category_tree = get_tree_node_recursive(root_node, parent_to_child_dict)

        biolink_version = biolink_model["version"]
        return [category_tree], biolink_version
    else:
        return [], ""


@app.route("/")
@app.route("/<biolink_version>")
@app.route("/categories")
@app.route("/categories/<biolink_version>")
def categories(biolink_version=None):
    category_tree, biolink_version = load_category_tree_data(biolink_version)
    return render_template("categories.html",
                           categories=category_tree,
                           biolink_version=biolink_version)


@app.route("/predicates")
@app.route("/predicates/<biolink_version>")
def predicates(biolink_version=None):
    predicate_tree, biolink_version = load_predicate_tree_data(biolink_version)
    return render_template("predicates.html",
                           predicates=predicate_tree,
                           biolink_version=biolink_version)


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--debug", dest="debug", action='store_true', default=False)
    args = arg_parser.parse_args()

    app.run(debug=args.debug)
