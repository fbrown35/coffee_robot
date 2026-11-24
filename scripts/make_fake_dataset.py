#!/usr/bin/env python
"""학습 환경 점검용 '가짜' 데이터셋 생성 (로봇 없이).

실제 녹화(coffee-lerobot record)와 같은 형식으로 만든다:
  observation.state / action : SO-100 관절 6개
  observation.images.camera1 / camera2 : 비디오
  task : config.yaml 의 스킬 지시문

    python scripts/make_fake_dataset.py --root /tmp/fake_coffee --episodes 2
    lerobot-train ... --dataset.repo_id=local/fake_coffee --dataset.root=/tmp/fake_coffee

학습 명령이 끝까지 도는지만 확인하는 용도이며, 이 데이터로 학습한 모델은 쓸모가 없다.
"""
import argparse
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

JOINTS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def main() -> None:
    from lerobot.datasets import LeRobotDataset
    from lerobot.utils.feature_utils import hw_to_dataset_features

    from coffee_robot.config import load_config

    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--repo-id", default="local/fake_coffee")
    ap.add_argument("--episodes", type=int, default=2)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--width", type=int, default=640)
    args = ap.parse_args()

    cfg = load_config()
    fps = int(cfg["policy"].get("fps", 30))
    tasks = [s["task"] for s in cfg["skills"].values()]
    hw = {f"{j}.pos": float for j in JOINTS}
    cams = {name: (args.height, args.width, 3) for name in cfg["cameras"]["devices"]}
    features = {**hw_to_dataset_features(hw, "action"), **hw_to_dataset_features({**hw, **cams}, "observation")}

    root = Path(args.root)
    if root.exists():
        shutil.rmtree(root)
    ds = LeRobotDataset.create(args.repo_id, fps, features, root=root, robot_type="so100_follower")
    rng = np.random.default_rng(0)
    for ep in range(args.episodes):
        task = tasks[ep % len(tasks)]
        start = rng.uniform(-30, 30, 6).astype(np.float32)
        for t in range(args.frames):
            state = start + np.float32(t * 0.2)
            frame = {
                "observation.state": state,
                "action": state + np.float32(0.2),
                "task": task,
            }
            for name in cams:
                frame[f"observation.images.{name}"] = rng.integers(0, 255, cams[name], dtype=np.uint8)
            ds.add_frame(frame)
        ds.save_episode()
    ds.finalize()
    print(f"OK: {args.episodes} episodes x {args.frames} frames -> {root}")


if __name__ == "__main__":
    main()
