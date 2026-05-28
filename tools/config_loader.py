import os
from pathlib import Path
import yaml

class Config(dict):
    def get(self, path, default=None):
        if path is None:
            return default
        parts = path.split('.')
        node = self
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node


def find_config_path():
    path = os.getenv('CONFIG_PATH')
    if path:
        candidate = Path(path)
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f'CONFIG_PATH set but not found: {candidate}')

    current = Path(__file__).resolve()
    for parent in [current.parent] + list(current.parents):
        candidate = parent / 'config.yaml'
        if candidate.exists():
            return candidate
    raise FileNotFoundError('config.yaml not found in repository tree. Set CONFIG_PATH or place config.yaml at repo root.')


def load_config(path=None):
    config_path = Path(path) if path else find_config_path()
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return Config(data or {})
