import yaml

from coffee_robot.config import load_config
from coffee_robot.lerobot_launcher import build, cameras_arg, parser


def test_cameras_arg_is_valid_yaml_dict():
    cams = yaml.safe_load(cameras_arg(load_config()))
    assert set(cams) == {"camera1", "camera2"}
    assert cams["camera2"]["type"] == "zmq" and cams["camera2"]["camera_name"] == "camera2"


def test_record_args():
    cfg = load_config()
    mod, args = build(cfg, parser().parse_args(["record", "place_cup", "--repo-id", "me/coffee", "--resume"]))
    assert mod == "lerobot.scripts.lerobot_record"
    assert f"--dataset.single_task={cfg['skills']['place_cup']['task']}" in args
    assert "--resume=true" in args and "--teleop.type=so100_leader" in args


def test_rollout_keeps_torque():
    mod, args = build(load_config(), parser().parse_args(["rollout", "--interactive"]))
    assert mod == "lerobot.scripts.lerobot_rollout"
    assert "--robot.disable_torque_on_disconnect=false" in args and "--interactive=true" in args
