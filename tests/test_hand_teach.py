import numpy as np
import pytest

from coffee_robot.hand_teach import (
    ARM, GRIPPER, JOINTS, KEYS, HandTeacher, ScriptedKeys, interpolate, smooth, to_action, trim_idle,
)


class FakeBus:
    def __init__(self, robot):
        self.robot = robot
        self.torque = {j: True for j in JOINTS}
        self.writes = []

    def sync_read(self, name, motors=None):
        assert name == "Present_Position"
        return {j: float(v) for j, v in zip(JOINTS, self.robot.pos, strict=True)}

    def sync_write(self, name, values):
        self.writes.append((name, dict(values)))
        for j, v in values.items():
            if self.torque[j]:
                self.robot.pos[JOINTS.index(j)] = v

    def enable_torque(self, motors=None):
        for j in motors or JOINTS:
            self.torque[j] = True

    def disable_torque(self, motors=None):
        for j in motors or JOINTS:
            self.torque[j] = False


class FakeRobot:
    """SOFollower 와 같은 인터페이스의 가짜 로봇. hand_path 로 '사람 손'이 팔을 움직이는 것을 흉내."""

    robot_type = "so_follower"
    name = "so_follower"

    def __init__(self, hand_path=None, cam_shape=(48, 64, 3)):
        self.pos = np.zeros(6, dtype=np.float32)
        self.pos[-1] = 50.0
        self.bus = FakeBus(self)
        self.hand_path = list(hand_path or [])
        self.cam_shape = cam_shape
        self.cameras = {"camera1": None, "camera2": None}
        self.sent = []
        self.connected = False

    @property
    def observation_features(self):
        return {**{k: float for k in KEYS}, "camera1": self.cam_shape, "camera2": self.cam_shape}

    @property
    def action_features(self):
        return {k: float for k in KEYS}

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def step_hand(self):
        if self.hand_path and not any(self.bus.torque[j] for j in ARM):
            self.pos[:5] = self.hand_path.pop(0)

    def get_observation(self):
        obs = {k: float(v) for k, v in zip(KEYS, self.pos, strict=True)}
        for c in self.cameras:
            obs[c] = np.full(self.cam_shape, int(self.pos[0]) % 255, dtype=np.uint8)
        return obs

    def send_action(self, action):
        self.sent.append(dict(action))
        self.bus.sync_write("Goal_Position", {k.removesuffix(".pos"): v for k, v in action.items()})
        return action


def test_smooth_keeps_gripper_and_reduces_noise():
    rng = np.random.default_rng(0)
    t = np.linspace(0, 1, 90)
    clean = np.stack([t * 30] * 5 + [np.where(t > 0.5, 10.0, 60.0)], axis=1).astype(np.float32)
    noisy = clean.copy()
    noisy[:, :5] += rng.normal(0, 1.0, (90, 5))
    out = smooth(noisy, window=5)
    assert out.shape == noisy.shape
    assert np.abs(out[5:-5, :5] - clean[5:-5, :5]).mean() < np.abs(noisy[5:-5, :5] - clean[5:-5, :5]).mean()
    assert np.array_equal(out[:, 5], noisy[:, 5])   # 그리퍼는 그대로


def test_trim_idle_keeps_margin():
    still = np.zeros((40, 6), dtype=np.float32)
    move = np.cumsum(np.ones((20, 6), dtype=np.float32), axis=0)
    traj = np.concatenate([still, move, np.repeat(move[-1:], 40, axis=0)])
    out = trim_idle(traj, thresh=0.5, keep=10)
    assert 20 <= len(out) <= 20 + 2 * 10 + 2
    assert np.allclose(out[-1], move[-1])


def test_interpolate_endpoints_and_monotonic():
    a, b = np.zeros(6, np.float32), np.arange(6, dtype=np.float32) * 10
    path = interpolate(a, b, 30)
    assert np.allclose(path[0], a) and np.allclose(path[-1], b)
    assert np.all(np.diff(path[:, 5]) >= 0)


def test_to_action_keys():
    assert list(to_action(np.arange(6))) == KEYS


def test_capture_records_hand_motion_and_commanded_gripper():
    hand = [np.full(5, float(i)) for i in range(1, 31)]
    robot = FakeRobot(hand_path=hand)
    teacher = HandTeacher(robot, fps=30, grip_step=5, sleep=lambda s: robot.step_hand(), printer=lambda s: None)
    # 시작 → 그리퍼 2번 닫기 → 몇 프레임 → 끝
    keys = ScriptedKeys([[" "], [], ["j", "j"]] + [[] for _ in range(10)] + [[" "]])
    traj = teacher.capture(keys, max_s=30)
    assert traj is not None and traj.shape[1] == 6 and len(traj) >= 10
    assert traj[-1, 5] == pytest.approx(40.0)          # 50 - 2*5: 명령한 그리퍼 값
    assert traj[-1, 0] > traj[0, 0]                     # 손이 움직인 궤적이 기록됨
    assert all(not robot.bus.torque[j] for j in ARM) and robot.bus.torque[GRIPPER]


def test_capture_cancel_returns_none():
    robot = FakeRobot()
    teacher = HandTeacher(robot, sleep=lambda s: None, printer=lambda s: None)
    assert teacher.capture(ScriptedKeys([[" "], [], ["q"]]), max_s=5) is None


def test_enable_torque_sets_goal_to_present_first():
    robot = FakeRobot()
    robot.bus.disable_torque(ARM)
    robot.pos[:5] = 12.0                                # 손으로 옮겨 둔 자세
    HandTeacher(robot, printer=lambda s: None)._enable_all_safely()
    name, values = robot.bus.writes[-1]
    assert name == "Goal_Position" and values["shoulder_pan"] == 12.0
    assert all(robot.bus.torque.values())


def test_replay_writes_lerobot_dataset(tmp_path):
    """LeRobot 이 설치된 환경에서만: 재생 녹화가 lerobot-record 와 같은 형식의 데이터셋을 만든다."""
    pytest.importorskip("lerobot")
    from lerobot.datasets import LeRobotDataset

    from coffee_robot.hand_teach import dataset_features, open_dataset

    robot = FakeRobot()
    teacher = HandTeacher(robot, fps=30, sleep=lambda s: None, printer=lambda s: None)
    root = tmp_path / "ds"
    ds = open_dataset("local/hand_test", robot, 30, root=str(root))
    traj = interpolate(np.zeros(6, np.float32), np.array([10, 20, 30, 40, 50, 20], np.float32), 30)
    n = teacher.replay(traj, ds, "press the start button", hold_s=0.2)
    ds.save_episode()
    ds.finalize()
    assert n == 30 + 6
    assert set(dataset_features(robot)) <= set(ds.features)

    # 이어서 쓰기 (두 번째 스킬)
    ds2 = open_dataset("local/hand_test", robot, 30, root=str(root))
    teacher.replay(traj, ds2, "press the espresso button", hold_s=0.2)
    ds2.save_episode()
    ds2.finalize()

    loaded = LeRobotDataset("local/hand_test", root=str(root))
    assert loaded.num_episodes == 2 and loaded.num_frames == 2 * n
    item = loaded[n - 1]
    assert item["action"].shape[-1] == 6 and "observation.images.camera1" in item
    assert {loaded[0]["task"], loaded[n]["task"]} == {"press the start button", "press the espresso button"}
