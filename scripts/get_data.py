from genericpath import exists
import json
from ntpath import join
import os
import sys
import unicodedata
import re
from typing import List
import argparse

from pyDataverse.api import DataAccessApi, NativeApi

# from pyDataverse.models import Dataverse
from pyDataverse.models import Dataset
from pyDataverse.exceptions import ApiAuthorizationError

config_template = {
    "dataverse_url": "https://darus.uni-stuttgart.de/",
    "datasets": [
        "doi:10.18419/darus-????",
    ],
    "options": {"downloadExistingData": "N"},
}


def get_script_path() -> str:
    return os.path.dirname(os.path.realpath(sys.argv[0]))


def get_search_dirs() -> List[str]:
    return [
        get_script_path(),
        os.path.join(get_script_path(), ".."),
        os.path.join(get_script_path(), "../.."),
    ]


def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


def create_config_template_if_needed() -> bool:
    config_file = os.path.join(get_script_path(), "darus_config.json")
    if not any(
        [
            os.path.exists(os.path.join(config_dir, "darus_config.json"))
            for config_dir in get_search_dirs()
        ]
    ):
        print("No configuration file exists.")
        with open(os.path.join(get_script_path(), "darus_config.json"), "w") as cf:
            json.dump(config_template, cf, indent=4)
        print(
            "Created a config template.\nRemember to fill in your dataset identifiers and crate a .darus_apikey file for your API key."
        )
        return True
    else:
        return False


def load_api_key_from_file():
    for d in get_search_dirs():
        path = os.path.join(d, ".darus_apikey")
        if os.path.exists(path):
            with open(path, "r") as key_file:
                return key_file.read()

    print("no file .darus_apikey found. Proceeding with public authentication.")
    return None


def load_config_from_file():
    config_txt = ""
    for d in get_search_dirs():
        path = os.path.join(d, "darus_config.json")
        if os.path.exists(path):
            with open(path, "r") as config_file:
                config_txt = config_file.read()
            break

    return json.loads(config_txt)


if __name__ == "__main__":
    if create_config_template_if_needed():
        exit(0)
    config_obj = load_config_from_file()
    api_key = load_api_key_from_file()

    # check user input
    try:
        parser = argparse.ArgumentParser(
            description="Download DaRUS Dataverses",
            epilog="Loads DaRUS Dataverses specify the Dataverse URL as command line argument, otherwise the configruation file is used.",
        )
        parser.add_argument(
            "--doi",
            type=str,
            nargs="*",
            default=None,
            required=False,
            help="data set identifier for data set to download",
        )
        args = parser.parse_args()
        user_provided_identifiers = args.doi
    except KeyboardInterrupt:
        print("User has exited the program")

    # get info for download
    dataverse_url = config_obj["dataverse_url"]
    if user_provided_identifiers is not None:
        dataset_identifiers = user_provided_identifiers
    else:
        dataset_identifiers = config_obj["datasets"]

    # download
    if api_key:
        api = NativeApi(dataverse_url, api_token=api_key)
        data_api = DataAccessApi(dataverse_url, api_token=api_key)
    else:  # no api key provided. assuming public dataset.
        api = NativeApi(dataverse_url)
        data_api = DataAccessApi(dataverse_url)

    for dataset_identifier in dataset_identifiers:
        try:
            dataset_ref = api.get_dataset(dataset_identifier)
            # print(json.dumps(dataset_ref.json(), indent=4))
            if dataset_ref.json()["status"] == "OK":
                dataset = Dataset(dataset_ref.json()["data"])
                # print(dataset.get()["title"])

                citation_info = dataset.get()["latestVersion"]["metadataBlocks"][
                    "citation"
                ]["fields"]
                title = ""
                for c in citation_info:
                    if c["typeName"] == "title":
                        title = c["value"]
                        break
                folder_name = slugify(title)  # extract from JSON
                folder = os.path.normpath(
                    os.path.join(get_script_path(), "..", "data", folder_name)
                )
                if os.path.exists(folder):
                    if config_obj["options"]["downloadExistingData"] == "N":
                        continue
                    elif config_obj["options"]["downloadExsistingData"] == "Y":
                        pass
                    else:
                        download_data = input(
                            f"The folder {folder} already exists. Do you want to download it again? (y/n)"
                        )
                        if download_data.lower() == "n":
                            continue
                os.makedirs(folder, exist_ok=True)

                files_list = dataset_ref.json()["data"]["latestVersion"]["files"]
                print("Downloading...")
                for file in files_list:
                    filename = file["dataFile"]["filename"]
                    print("File: {}".format(filename))
                    if "directoryLabel" in file:  # need if dataset has folderstructure
                        folderpath = file["directoryLabel"]
                    else:
                        folderpath = ""
                    file_id = file["dataFile"]["id"]
                    response = data_api.get_datafile(file_id)
                    fullpath = os.path.join(folder, folderpath, filename)
                    os.makedirs(os.path.dirname(fullpath), exist_ok=True)
                    with open(fullpath, "wb") as f:
                        f.write(response.content)

                with open(os.path.join(folder, "info.json"), "w") as json_metadata_f:
                    metadata = dataset_ref.json()["data"]
                    json.dump(metadata, json_metadata_f, indent=4)
                print("Done.")
        except ApiAuthorizationError as e:
            no_key_given = "" if api_key else "without API key"
            print("Cannot access data with id:", dataset_identifier, no_key_given, ".")
            print(e)
