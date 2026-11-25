"""리더 암 없이 데모 녹화: '손으로 가르치기 → 로봇이 재생하며 녹화'.

리더 암이 없을 때 쓰는 방법이다. 에피소드마다 두 단계를 거친다.

1. 가르치기(캡처)
   - 팔 관절 5개의 토크를 끄고, 사람이 손으로 팔을 잡고 동작을 보여 준다.
   - 그리퍼는 토크를 켠 채 키보드(j/k)로 열고 닫는다. 컵을 확실히 쥐게 하려고 키로 조절한다.
   - 이 단계에서는 관절 궤적만 저장하고 카메라 영상은 저장하지 않는다. 영상에 사람 손이 찍히기 때문이다.
2. 재생 녹화
   - 장면을 시작 상태로 되돌린다(컵 위치, 커피머신 상태).
   - 로봇이 토크를 켜고 같은 궤적을 스스로 따라 움직인다.
   - 이때 카메라 영상, 관절 상태, 명령(action)을 LeRobot 데이터셋에 기록한다.
   - 영상에는 손이 없는 '로봇 혼자 하는 모습'만 남아서 실제 실행할 때와 조건이 같다.

데이터셋 형식(특징 이름, 로봇 타입, fps)은 lerobot-record 와 같다.
그래서 나중에 리더 암이 생기면 같은 데이터셋에 lerobot-record --resume 으로 이어서 녹화할 수 있다.

    coffee-hand-record place_cup --repo-id <hf_user>/coffee_skills [--episodes 22]
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import select
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

log = logging.getLogger(__name__)

ARM = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
GRIPPER = "gripper"
JOINTS = ARM + [GRIPPER]
KEYS = [f"{j}.pos" for j in JOINTS]


# ─────────────────────────── 궤적 처리 (순수 함수) ───────────────────────────
def smooth(traj: np.ndarray, window: int = 5) -> np.ndarray:
    """손떨림 제거: 팔 관절에만 이동 평균을 적용한다. 그리퍼(마지막 열)는 키 입력값 그대로 둔다."""
    if window <= 1 or len(traj) < window:
        return traj.copy()
    out = traj.astype(np.float64).copy()
    pad = window // 2
    kernel = np.ones(window) / window
    for j in range(traj.shape[1] - 1):
        col = np.pad(traj[:, j].astype(np.float64), (pad, window - 1 - pad), mode="edge")
        out[:, j] = np.convolve(col, kernel, mode="valid")
    return out.astype(np.float32)


def trim_idle(traj: np.ndarray, thresh: float = 0.5, keep: int = 15) -> np.ndarray:
    """시작과 끝에서 움직임이 없는 구간을 잘라내되, 앞뒤로 keep 프레임은 남긴다."""
    if len(traj) < 2:
        return traj
    step = np.abs(np.diff(traj, axis=0)).max(axis=1)
    moving = np.nonzero(step > thresh)[0]
    if moving.size == 0:
        return traj
    start = max(0, moving[0] - keep)
    end = min(len(traj), moving[-1] + 2 + keep)
    return traj[start:end]


def interpolate(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    """a 에서 b 로 n 단계에 걸쳐 부드럽게 이동 (코사인 가속/감속)."""
    t = (1 - np.cos(np.linspace(0, np.pi, max(n, 1)))) / 2
    return (a[None, :] + (b - a)[None, :] * t[:, None]).astype(np.float32)


def to_action(row: np.ndarray) -> dict[str, float]:
    return {k: float(v) for k, v in zip(KEYS, row, strict=True)}


# ─────────────────────────── 키 입력 ───────────────────────────
class KeySource(Protocol):
    def poll(self) -> list[str]: ...


class TerminalKeys:
    """터미널에서 Enter 없이 키를 한 글자씩 읽는다 (macOS, Linux). 추가 권한이 필요 없다."""

    def __init__(self, stream=None):
        self.stream = stream or sys.stdin
        self._buf: list[str] = []
        self._lock = threading.Lock()
        self._old = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "TerminalKeys":
        import termios
        import tty

        fd = self.stream.fileno()
        self._old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        import termios

        self._stop.set()
        if self._thread:
            self._thread.join(0.5)
        if self._old is not None:
            termios.tcsetattr(self.stream.fileno(), termios.TCSADRAIN, self._old)

    def _run(self) -> None:
        fd = self.stream.fileno()
        while not self._stop.is_set():
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                ch = os.read(fd, 1).decode(errors="ignore")
                with self._lock:
                    self._buf.append(ch)

    def poll(self) -> list[str]:
        with self._lock:
            out, self._buf = self._buf, []
        return out


class ScriptedKeys:
    """테스트용: poll() 할 때마다 정해진 키 묶음을 차례로 돌려준다."""

    def __init__(self, script: Iterable[list[str]]):
        self._it = iter(script)

    def poll(self) -> list[str]:
        return next(self._it, [])


# ─────────────────────────── 가르치기 / 재생 ───────────────────────────
class HandTeacher:
    def __init__(self, robot: Any, fps: int = 30, grip_step: float = 3.0,
                 sleep: Callable[[float], None] = time.sleep, printer: Callable[[str], None] = print):
        self.robot = robot
        self.fps = fps
        self.grip_step = grip_step
        self.sleep = sleep
        self.printer = printer

    @property
    def bus(self):
        return self.robot.bus

    def _present(self) -> np.ndarray:
        pos = self.bus.sync_read("Present_Position")
        return np.array([pos[j] for j in JOINTS], dtype=np.float32)

    def _enable_all_safely(self) -> None:
        """토크를 켜기 전에 목표 위치를 현재 위치로 맞춘다. 그래야 켜는 순간 팔이 튀지 않는다."""
        present = self._present()
        self.bus.sync_write("Goal_Position", {j: float(v) for j, v in zip(JOINTS, present, strict=True)})
        self.bus.enable_torque()

    def capture(self, keys: KeySource, max_s: float) -> np.ndarray | None:
        """손으로 가르친 궤적(N x 6)을 반환한다. 취소하면 None 을 반환한다.

        키: Space = 시작/끝, j/k = 그리퍼 닫기/열기 방향으로 조금씩, q = 취소
        """
        self._enable_all_safely()
        self.bus.disable_torque(ARM)                     # 팔은 손으로, 그리퍼는 키로
        grip = float(self._present()[-1])
        self.printer("  팔의 토크를 껐습니다. 한 손으로 팔을 받친 채 홈 자세에 두세요.")
        self.printer("  [Space] 가르치기 시작/끝   [j]/[k] 그리퍼 조절(누르고 있으면 계속)   [q] 취소")
        recording = False
        rows: list[np.ndarray] = []
        period = 1.0 / self.fps
        t_start = None
        last_info = 0.0
        grip_changed = False
        while True:
            t0 = time.perf_counter()
            for k in keys.poll():
                if k == " ":
                    if not recording:
                        recording, t_start = True, time.perf_counter()
                        self.printer("  ● 가르치는 중… 동작이 끝나면 홈 자세로 돌아와 [Space]")
                    else:
                        recording = False
                        self.printer(f"  ■ 끝 ({len(rows)}프레임, {len(rows) / self.fps:.1f}초)")
                        return np.stack(rows) if rows else None
                elif k in ("j", "k"):
                    grip = float(np.clip(grip + (-self.grip_step if k == "j" else self.grip_step), 0, 100))
                    self.robot.send_action({f"{GRIPPER}.pos": grip})
                    grip_changed = True
                elif k == "q":
                    self.printer("  취소했습니다.")
                    return None
            if recording:
                pos = self._present()
                pos[-1] = grip                          # 그리퍼는 '명령한 값'을 기록 (재생 때 그대로 쥐도록)
                rows.append(pos)
                if t_start is not None and time.perf_counter() - t_start > max_s:
                    self.printer(f"  최대 시간({max_s:.0f}초)이 지나 자동으로 끝냈습니다.")
                    return np.stack(rows)
            now = time.perf_counter()
            if grip_changed and now - last_info > 0.3:     # 그리퍼를 조절할 때만 값 표시
                self.printer(f"  그리퍼 값: {grip:5.1f}")
                last_info, grip_changed = now, False
            self.sleep(max(0.0, period - (time.perf_counter() - t0)))

    def move_to(self, target: np.ndarray, seconds: float = 2.0) -> None:
        """녹화하지 않고 현재 자세에서 target 으로 천천히 이동한다."""
        start = self._present()
        for row in interpolate(start, target, int(seconds * self.fps)):
            self.robot.send_action(to_action(row))
            self.sleep(1.0 / self.fps)

    def replay(self, traj: np.ndarray, dataset: Any, task: str, hold_s: float = 1.0) -> int:
        """궤적을 재생하면서 데이터셋 버퍼에 프레임을 쌓는다. save_episode 는 호출하는 쪽에서 한다."""
        from lerobot.utils.constants import ACTION, OBS_STR
        from lerobot.utils.feature_utils import build_dataset_frame

        self._enable_all_safely()
        self.move_to(traj[0])
        self.sleep(0.5)
        hold = np.repeat(traj[-1:], int(hold_s * self.fps), axis=0)
        frames = 0
        period = 1.0 / self.fps
        for row in np.concatenate([traj, hold]):
            t0 = time.perf_counter()
            obs = self.robot.get_observation()          # lerobot-record 와 같은 순서: 관측 → 명령 → 기록
            action = to_action(row)
            self.robot.send_action(action)
            frame = {**build_dataset_frame(dataset.features, obs, prefix=OBS_STR),
                     **build_dataset_frame(dataset.features, action, prefix=ACTION),
                     "task": task}
            dataset.add_frame(frame)
            frames += 1
            self.sleep(max(0.0, period - (time.perf_counter() - t0)))
        return frames


# ─────────────────────────── LeRobot 연결 ───────────────────────────
def make_robot(cfg: dict[str, Any]):
    """config.yaml 로 lerobot-record 와 같은 설정의 로봇을 만든다."""
    import lerobot.robots.so_follower  # noqa: F401  (설정 클래스 등록)
    from lerobot.cameras.zmq import ZMQCameraConfig
    from lerobot.robots import RobotConfig
    from lerobot.robots.utils import make_robot_from_config

    from .config import expand

    r, cams = cfg["robot"], cfg["cameras"]
    cameras = {
        name: ZMQCameraConfig(server_address=cams.get("hub_host", "127.0.0.1"), port=cams.get("hub_port", 5555),
                              camera_name=name, width=spec.get("width", 640), height=spec.get("height", 480),
                              fps=spec.get("fps", 30))
        for name, spec in cams["devices"].items()
    }
    rc = RobotConfig.get_choice_class(r["type"])(
        port=expand(r["port"]), id=r["id"], cameras=cameras, max_relative_target=r.get("max_relative_target"))
    return make_robot_from_config(rc)


def dataset_features(robot: Any, use_videos: bool = True) -> dict[str, dict]:
    """lerobot-record 와 같은 방법으로 데이터셋 특징을 만든다 (기본 처리기 = 그대로 통과)."""
    from lerobot.datasets import aggregate_pipeline_dataset_features, create_initial_features
    from lerobot.processor import make_default_processors
    from lerobot.utils.feature_utils import combine_feature_dicts

    teleop_proc, _, obs_proc = make_default_processors()
    return combine_feature_dicts(
        aggregate_pipeline_dataset_features(pipeline=teleop_proc,
                                            initial_features=create_initial_features(action=robot.action_features),
                                            use_videos=use_videos),
        aggregate_pipeline_dataset_features(pipeline=obs_proc,
                                            initial_features=create_initial_features(
                                                observation=robot.observation_features),
                                            use_videos=use_videos),
    )


def open_dataset(repo_id: str, robot: Any, fps: int, root: str | None = None):
    """데이터셋이 있으면 이어서 쓰고, 없으면 새로 만든다."""
    from lerobot.datasets import LeRobotDataset
    from lerobot.utils.constants import HF_LEROBOT_HOME

    path = Path(root) if root else HF_LEROBOT_HOME / repo_id
    n_cams = len(getattr(robot, "cameras", {}))
    if (path / "meta" / "info.json").exists():
        ds = LeRobotDataset.resume(repo_id, root=root, image_writer_threads=4 * n_cams)
        if ds.fps != fps:
            raise ValueError(f"기존 데이터셋 fps({ds.fps})와 설정 fps({fps})가 다릅니다.")
        missing = set(dataset_features(robot)) - set(ds.features)
        if missing:
            raise ValueError(f"기존 데이터셋과 특징이 다릅니다(카메라 이름/개수 확인): {sorted(missing)}")
        return ds
    return LeRobotDataset.create(repo_id, fps, features=dataset_features(robot), root=root,
                                 robot_type=robot.robot_type, use_videos=True, image_writer_threads=4 * n_cams)


# ─────────────────────────── 실행 ───────────────────────────
def run(cfg: dict[str, Any], skill: str, repo_id: str, episodes: int | None, root: str | None,
        traj_dir: Path, robot=None, keys_factory=TerminalKeys, ask: Callable[[str], str] = input,
        printer: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep) -> int:
    sk = cfg["skills"][skill]
    fps = int(cfg["policy"].get("fps", 30))
    total = episodes or int(sk.get("demos", 10))
    max_s = float(sk.get("timeout_s", 20)) + 5
    robot = robot or make_robot(cfg)
    robot.connect()
    dataset = open_dataset(repo_id, robot, fps, root)
    teacher = HandTeacher(robot, fps, sleep=sleep, printer=printer)
    traj_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    try:
        while saved < total:
            printer(f"\n=== [{skill}] 에피소드 {saved + 1}/{total}  —  \"{sk['task']}\" ===")
            printer("  ① 가르치기: 터치 팁 접지선을 빼 두면 버튼이 실제로 눌리지 않습니다(머신 상태 유지).")
            with keys_factory() as keys:
                raw = teacher.capture(keys, max_s)
            if raw is None:
                if ask("  다시 가르치려면 Enter, 이 스킬을 끝내려면 q: ").strip().lower() == "q":
                    break
                continue
            traj = smooth(trim_idle(raw))
            np.save(traj_dir / f"{skill}_{time.strftime('%Y%m%d_%H%M%S')}.npy", traj)
            while True:
                ask("  ② 장면을 시작 상태로 되돌리고(컵 위치, 머신 상태, 접지선 연결) Enter → 로봇이 재생하며 녹화")
                frames = teacher.replay(traj, dataset, sk["task"])
                ans = ask(f"  녹화 {frames}프레임. 저장하려면 Enter, 다시 재생은 r, 버리기는 x: ").strip().lower()
                if ans == "r":
                    dataset.clear_episode_buffer()
                    continue
                if ans == "x":
                    dataset.clear_episode_buffer()
                    printer("  버렸습니다. 다시 가르칩니다.")
                    break
                dataset.save_episode()
                saved += 1
                printer(f"  저장했습니다 ({saved}/{total}).")
                break
    finally:
        if getattr(dataset, "has_pending_frames", lambda: False)():
            dataset.clear_episode_buffer()
        dataset.finalize()
        printer("\n  곧 토크가 꺼집니다. 팔을 받쳐 주세요.")
        sleep(2.0)
        robot.disconnect()
    printer(f"\n[{skill}] {saved}개 저장 완료 → {repo_id}")
    return saved


def main(argv: list[str] | None = None) -> None:
    from .config import ROOT, load_config
    from .lerobot_launcher import patch_bus_timeout

    ap = argparse.ArgumentParser(description="리더 암 없이 데모 녹화 (손으로 가르치기 → 재생 녹화)")
    ap.add_argument("skill", help="config.yaml 의 skills 이름 (예: place_cup)")
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--episodes", type=int, default=None, help="저장할 에피소드 수 (기본: skills.<이름>.demos)")
    ap.add_argument("--root", default=None, help="데이터셋 폴더 (기본: ~/.cache/huggingface/lerobot/<repo_id>)")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    cfg = load_config(args.config)
    patch_bus_timeout(int(cfg["robot"].get("bus_timeout_ms", 50)))
    with contextlib.suppress(KeyboardInterrupt):
        run(cfg, args.skill, args.repo_id, args.episodes, args.root, ROOT / "data" / "trajectories")


if __name__ == "__main__":
    main()
