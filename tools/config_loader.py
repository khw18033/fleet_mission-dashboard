import logging
import os
from pathlib import Path
import yaml

log = logging.getLogger("config_loader")

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
    """config.yaml 경로를 찾는다.

    - CONFIG_PATH가 지정됐는데 파일이 없으면 명시적 오설정이므로 예외를 던진다.
    - 지정이 없고 저장소 트리에서도 못 찾으면 None을 반환한다. 컨테이너에는
      config.yaml을 굽지 않고 env/ConfigMap으로만 설정을 주입하는 경우가 있으므로
      파일 부재는 오류가 아니다(load_config가 빈 설정으로 폴백).
    """
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
    return None


def load_config(path=None):
    config_path = Path(path) if path else find_config_path()
    if config_path is None:
        log.warning('config.yaml not found — env/ConfigMap 설정만으로 동작 (빈 설정 폴백)')
        return Config({})
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return Config(data or {})
