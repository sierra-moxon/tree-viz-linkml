# Thanks https://towardsdatascience.com/create-and-deploy-a-simple-web-application-with-flask-and-heroku-103d867298eb
import argparse
from collections import defaultdict
from typing import Tuple, List

import requests
import yaml
from flask import Flask, render_template, jsonify
from flask_cors import cross_origin

app = Flask(__name__)


def convert_predicate_to_trapi_format(english_predicate: str) -> str:
    # Converts a string like "treated by" to "treated_by"
    return english_predicate.replace(' ', '_')


def convert_category_to_trapi_format(english_category: str) -> str:
    # Converts a string like "named thing" to "NamedThing"
    return "".join([f"{word[0].upper()}{word[1:]}" for word in english_category.split(" ")])


def get_tree_node_recursive(root_node: dict, parent_to_child_map: dict):
    root_name = root_node["name"]
    children_names = parent_to_child_map.get(root_name, [])
    if children_names:
        children = []
        for child_name in children_names:
            child_node = {"name": child_name, "parent": root_name}
            child_node = get_tree_node_recursive(child_node, parent_to_child_map)
            children.append(child_node)
        root_node["children"] = sorted(children, key=lambda x: x["name"])
    return root_node


def get_linkml_data(linkml_version: str) -> requests.Response:
    response = requests.get(f"https://raw.githubusercontent.com/linkml/linkml-model/"
                            f"{linkml_version if linkml_version else 'master'}/linkml-model.yaml",
                            timeout=10)
    if response.status_code != 200:  # Sometimes Biolink's tags start with 'v', so try that
        response = requests.get(f"https://raw.githubusercontent.com/linkml/linkml-model/v{linkml_version}/linkml-model.yaml",
                                timeout=10)
    return response


def load_predicate_tree_data(linkml_version: str) -> Tuple[List[dict], str]:
    # Grab Biolink yaml file and load into dictionary tree structures
    response = get_linkml_data(linkml_version)
    if response.status_code == 200:
        # Build predicates tree
        linkml_model = yaml.safe_load(response.text)
        parent_to_child_dict = defaultdict(set)
        for slot_name_english, info in linkml_model["slots"].items():
            slot_name = convert_predicate_to_trapi_format(slot_name_english)
            parent_name_english = info.get("is_a")
            if parent_name_english:
                parent_name = convert_predicate_to_trapi_format(parent_name_english)
                parent_to_child_dict[parent_name].add(slot_name)
        root_node = {"name": "related_to"}
        predicate_tree = get_tree_node_recursive(root_node, parent_to_child_dict)

        linkml_version = linkml_model["version"]
        return [predicate_tree], linkml_version
    else:
        return [], ""


def load_category_tree_data(linkml_version: str, return_parent_to_child_dict: bool = False) -> tuple:
    # Grab Biolink yaml file and load into dictionary tree structures
    response = get_linkml_data(linkml_version)
    if response.status_code == 200:
        # Build categories tree
        linkml_model = yaml.safe_load(response.text)
        parent_to_child_dict = defaultdict(set)
        for slot_name_english, info in linkml_model["classes"].items():
            slot_name = convert_category_to_trapi_format(slot_name_english)
            parent_name_english = info.get("is_a")
            if parent_name_english:
                parent_name = convert_category_to_trapi_format(parent_name_english)
                parent_to_child_dict[parent_name].add(slot_name)

        root_node = {"name": "NamedThing", "parent": None}
        category_tree = get_tree_node_recursive(root_node, parent_to_child_dict)

        linkml_version = linkml_model["version"]
        return ([category_tree], linkml_version, parent_to_child_dict) if return_parent_to_child_dict else ([category_tree], linkml_version)
    else:
        return ([], "", dict()) if return_parent_to_child_dict else ([], "")


def load_aspect_tree_data(linkml_version: str) -> Tuple[List[dict], str]:
    # Grab Biolink yaml file and load into dictionary tree structures
    response = get_linkml_data(linkml_version)
    if response.status_code == 200:
        linkml_model = yaml.safe_load(response.text)
        # Figure out if we're on a version of Biolink that has qualifier aspect info
        linkml_version = linkml_model["version"]
        if linkml_version >= "3.0.0":
            aspect_enum_field_name = "gene_or_gene_product_or_chemical_entity_aspect_enum" if linkml_version.startswith("3.0") else "GeneOrGeneProductOrChemicalEntityAspectEnum"
            # Build aspects tree
            parent_to_child_dict = defaultdict(set)
            root_name = "[root]"
            for aspect_name, info in linkml_model["enums"][aspect_enum_field_name]["permissible_values"].items():
                parent = info.get("is_a", root_name) if info else root_name
                parent_to_child_dict[parent].add(aspect_name)

            root_node = {"name": root_name, "parent": None}
            aspect_tree = get_tree_node_recursive(root_node, parent_to_child_dict)
        else:
            aspect_tree = dict()

        return [aspect_tree], linkml_version
    else:
        return [], ""


def load_category_er_tree_data(linkml_version: str, return_parent_to_child_dict: bool = False) -> tuple:
    # First build the standard category tree
    category_tree, linkml_version, parent_to_child_map = load_category_tree_data(linkml_version, return_parent_to_child_dict=True)
    child_to_parent_map = {child_name: parent_name for parent_name, children_names in parent_to_child_map.items()
                           for child_name in children_names}

    # Then move gene/protein-related subbranches under one new sub-branch within BiologicalEntity
    biological_entity_sub_branches = parent_to_child_map["BiologicalEntity"]
    sub_branches_to_keep = {"BiologicalProcessOrActivity", "DiseaseOrPhenotypicFeature", "OrganismalEntity"}
    sub_branches_to_move = biological_entity_sub_branches.difference(sub_branches_to_keep)
    new_sub_branch = "GeneticOrMolecularBiologicalEntity"
    for sub_branch_to_move in sub_branches_to_move:
        child_to_parent_map[sub_branch_to_move] = new_sub_branch
    parent_to_child_map_revised = defaultdict(set)
    for child, parent in child_to_parent_map.items():
        parent_to_child_map_revised[parent].add(child)
    parent_to_child_map_revised["BiologicalEntity"].add(new_sub_branch)

    root_node = {"name": "NamedThing", "parent": None}
    category_tree_for_er = get_tree_node_recursive(root_node, parent_to_child_map_revised)

    return ([category_tree_for_er], linkml_version, parent_to_child_map_revised) if return_parent_to_child_dict else ([category_tree_for_er], linkml_version)


def generate_major_branches_maps(linkml_version: str, for_entity_resolution: bool = False) -> dict:
    if for_entity_resolution:
        category_tree, linkml_version, parent_to_child_map = load_category_er_tree_data(linkml_version, return_parent_to_child_dict=True)
    else:
        category_tree, linkml_version, parent_to_child_map = load_category_tree_data(linkml_version, return_parent_to_child_dict=True)
    named_thing_node = category_tree[0]
    # Record which are our depth-one categories (first nodes off of 'NamedThing')
    # Exception is for BiologicalEntity branch, for entity resolution work; there we use the depth-two categories
    biological_entity = "BiologicalEntity"
    named_thing = "NamedThing"
    if for_entity_resolution:
        # Move biological entity's sub-branches up one level, onto named thing
        parent_to_child_map[named_thing] = parent_to_child_map[named_thing].union(parent_to_child_map[biological_entity])
        # Then remove the biological entity branch, since it no longer has any children
        parent_to_child_map[named_thing].remove(biological_entity)
        del parent_to_child_map[biological_entity]
    major_branches = parent_to_child_map[named_thing]

    # Map each child to its major branch ancestor
    child_to_parent_map = {child_name: parent_name for parent_name, children_names in parent_to_child_map.items()
                           for child_name in children_names}
    child_to_major_branch_map = dict()
    for child_name, parent_name in child_to_parent_map.items():
        if child_name in major_branches:
            # Record major branch categories as ancestors of themselves
            ancestor = child_name
        else:
            # Keep moving up the ancestral tree until we reach a major branch category
            ancestor = parent_name
            while ancestor and ancestor not in major_branches:
                ancestor = child_to_parent_map.get(ancestor)
        child_to_major_branch_map[child_name] = ancestor

    # Filter out null values (which must either be mixins or themselves major branch categories..)
    child_to_major_branch_map = {child: major_branch
                                 for child, major_branch in child_to_major_branch_map.items()
                                 if major_branch}

    major_branches_to_descendants_map = defaultdict(list)
    for child, depth_one_ancestor in child_to_major_branch_map.items():
        major_branches_to_descendants_map[depth_one_ancestor].append(child)

    return {"category_to_major_branch": child_to_major_branch_map,
            "major_branch_to_descendants": major_branches_to_descendants_map}


@app.route("/")
@app.route("/<linkml_version>")
@app.route("/categories")
@app.route("/categories/<linkml_version>")
def categories(linkml_version=None):
    category_tree, linkml_version = load_category_tree_data(linkml_version)
    return render_template("categories.html",
                           categories=category_tree,
                           linkml_version=linkml_version)


@app.route("/predicates")
@app.route("/predicates/<linkml_version>")
def predicates(linkml_version=None):
    predicate_tree, linkml_version = load_predicate_tree_data(linkml_version)
    return render_template("predicates.html",
                           predicates=predicate_tree,
                           linkml_version=linkml_version)


@app.route("/categories/er")
@app.route("/categories/er/<linkml_version>")
def categories_for_entity_resolution(linkml_version=None):
    category_tree_for_er, linkml_version = load_category_er_tree_data(linkml_version)
    return render_template("categories.html",
                           categories=category_tree_for_er,
                           linkml_version=linkml_version)


@app.route("/aspects")
@app.route("/aspects/<linkml_version>")
def aspects(linkml_version=None):
    aspect_tree, linkml_version = load_aspect_tree_data(linkml_version)
    return render_template("aspects.html",
                           aspects=aspect_tree,
                           linkml_version=linkml_version)


@app.route("/major_branches")
@app.route("/major_branches/<linkml_version>")
@cross_origin()
def get_major_branches_maps(linkml_version=None):
    maps = generate_major_branches_maps(linkml_version, for_entity_resolution=False)
    return jsonify(maps)


@app.route("/major_branches/er")
@app.route("/major_branches/er/<linkml_version>")
@cross_origin()
def get_major_branches_maps_for_entity_resolution(linkml_version=None):
    maps = generate_major_branches_maps(linkml_version, for_entity_resolution=True)
    return jsonify(maps)


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--debug", dest="debug", action='store_true', default=False)
    args = arg_parser.parse_args()

    app.run(debug=args.debug)
