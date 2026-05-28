"""
로봇 상태 heartbeat/오프라인 감지 및 Redis 동기화 (Phase 2)
- 각 로봇에서 heartbeat 신호를 주기적으로 전송
- central-hub에서 heartbeat timeout 감지 시 offline 처리
"""

import os
import time
from pathlib import Path

import redis
import yaml


class MockRedis:
    def __init__(self):
        self._data = {}

    def set(self, key, value):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)

    def ping(self):
        return True


def load_config():
    config_path = Path(os.environ.get('CONFIG_PATH', Path(__file__).resolve().parents[1] / 'config.yaml'))
    with open(config_path, 'r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


def update_heartbeat(r, robot_id):
    r.set(f'robot:heartbeat:{robot_id}', int(time.time()))
    r.set(f'robot:online:{robot_id}', 1)


def check_robots(r, robot_ids, timeout):
    now = int(time.time())
    for rid in robot_ids:
        hb = r.get(f'robot:heartbeat:{rid}')
        if hb and now - int(hb) < timeout:
            r.set(f'robot:online:{rid}', 1)
        else:
            r.set(f'robot:online:{rid}', 0)
            print(f'[HEARTBEAT] {rid} offline')


def build_redis_client(redis_conf):
    host = redis_conf.get('host', 'localhost')
    port = int(redis_conf.get('port', 6379))
    try:
        client = redis.Redis(host=host, port=port)
        client.ping()
        return client
    except Exception as exc:
        print(f'[HEARTBEAT] Redis unavailable, using mock store: {exc}')
        return MockRedis()


def main():
    config = load_config()
    redis_conf = config.get('redis', {})
    robot_ids = [robot.get('id') for robot in config.get('robots', []) if robot.get('id')]
    if not robot_ids:
        robot_ids = ['robot-mock']
    timeout = int(config.get('heartbeat', {}).get('timeout_sec', 10))
    redis_client = build_redis_client(redis_conf)

    while True:
        check_robots(redis_client, robot_ids, timeout)
        time.sleep(5)


if __name__ == '__main__':
    main()
