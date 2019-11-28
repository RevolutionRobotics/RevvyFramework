# SPDX-License-Identifier: GPL-3.0-only

import os

from revvy.functions import read_json


class Assets:
    def __init__(self, paths: list):
        self._files = {}
        for path in paths:
            self._load(path)

    def _load(self, path):
        assets_json = os.path.join(path, 'assets.json')
        # noinspection PyBroadException
        try:
            manifest = read_json(assets_json)
            files = manifest['files']
            for category, assets in files.items():
                if category not in self._files:
                    self._files[category] = {}

                for asset_name, asset_path in assets.items():
                    self._files[category][asset_name] = os.path.join(path, asset_path)
        except Exception:
            pass

    def get_asset_file(self, category, name):
        return self._files[category][name]
