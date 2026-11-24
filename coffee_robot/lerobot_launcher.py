"""LeRobot 0.7 CLI 래퍼: config.yaml 로 인자를 만들고, WiFi 지연에 맞게 버스 타임아웃을 늘린 뒤 실행.

    coffee-lerobot calibrate                     # follower 캘리브레이션
    coffee-lerobot calibrate-leader              # leader 캘리브레이션
    coffee-lerobot teleop                        # 텔레오퍼레이션 연습
    coffee-lerobot record place_cup --repo-id me/coffee_skills [--resume]
    coffee-lerobot rollout --task "press the start button" --duration 15
    coffee-lerobot rollout --interactive         # 오케스트레이터가 사용하는 모드

--print 를 붙이면 실행 대신 명령만 출력한다.
"""
from __future__ import annotations

import argparse
import shlex
import sys
from typing import Any

from .config import expand, load_config


def cameras_arg(cfg: dict[str, Any]) -> str:
    cams = cfg["cameras"]
    parts = []
    for name, spec in cams["devices"].items():
        parts.append(
            f"{name}: {{type: zmq, server_address: {cams.get('hub_host', '127.0.0.1')}, "
            f"port: {cams.get('hub_port', 5555)}, camera_name: {name}, "
            f"width: {spec.get('width', 640)}, height: {spec.get('height', 480)}, fps: {spec.get('fps', 30)}}}"
        )
    return "{ " + ", ".join(parts) + " }"


def robot_args(cfg: dict[str, Any], keep_torque: bool = False) -> list[str]:
    r = cfg["robot"]
    args = [
        f"--robot.type={r['type']}",
        f"--robot.port={expand(r['port'])}",
        f"--robot.id={r['id']}",
        f"--robot.cameras={cameras_arg(cfg)}",
    ]
    if r.get("max_relative_target"):
        args.append(f"--robot.max_relative_target={r['max_relative_target']}")
    if keep_torque:
        args.append("--robot.disable_torque_on_disconnect=false")
    return args


def teleop_args(cfg: dict[str, Any]) -> list[str]:
    t = cfg["teleop"]
    return [f"--teleop.type={t['type']}", f"--teleop.port={expand(t['port'])}", f"--teleop.id={t['id']}"]


def build(cfg: dict[str, Any], ns: argparse.Namespace) -> tuple[str, list[str]]:
    """(lerobot 스크립트 모듈, argv) 반환."""
    if ns.cmd == "calibrate":
        r = cfg["robot"]
        return "lerobot.scripts.lerobot_calibrate", [
            f"--robot.type={r['type']}", f"--robot.port={expand(r['port'])}", f"--robot.id={r['id']}"]
    if ns.cmd == "calibrate-leader":
        return "lerobot.scripts.lerobot_calibrate", teleop_args(cfg)
    if ns.cmd == "teleop":
        return "lerobot.scripts.lerobot_teleoperate", robot_args(cfg) + teleop_args(cfg) + ["--display_data=true"]
    if ns.cmd == "record":
        skill = cfg["skills"][ns.skill]
        argv = robot_args(cfg) + teleop_args(cfg) + [
            f"--dataset.repo_id={ns.repo_id}",
            f"--dataset.single_task={skill['task']}",
            f"--dataset.num_episodes={ns.episodes or skill.get('demos', 10)}",
            f"--dataset.episode_time_s={ns.episode_time or skill.get('timeout_s', 20) + 5}",
            f"--dataset.reset_time_s={ns.reset_time}",
            f"--dataset.fps={cfg['policy'].get('fps', 30)}",
            f"--dataset.push_to_hub={'true' if ns.push else 'false'}",
            "--display_data=true",
        ]
        if ns.resume:
            argv.append("--resume=true")
        return "lerobot.scripts.lerobot_record", argv
    if ns.cmd == "rollout":
        p = cfg["policy"]
        argv = robot_args(cfg, keep_torque=True) + [
            "--strategy.type=base",
            f"--policy.path={ns.policy or p['path']}",
            f"--inference.type={p.get('inference', 'sync')}",
            f"--fps={p.get('fps', 30)}",
        ]
        if p.get("device"):
            argv.append(f"--device={p['device']}")
        if ns.interactive:
            argv.append("--interactive=true")
        if ns.task:
            argv.append(f"--task={ns.task}")
        if ns.duration:
            argv.append(f"--duration={ns.duration}")
        return "lerobot.scripts.lerobot_rollout", argv
    raise SystemExit(f"unknown command {ns.cmd}")


def patch_bus_timeout(ms: int) -> None:
    """WiFi 왕복 지연 때문에 Feetech 응답이 50ms 를 넘을 수 있어 타임아웃을 늘린다."""
    from lerobot.motors.motors_bus import SerialMotorsBus

    SerialMotorsBus.default_timeout = ms


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="LeRobot 래퍼 (config.yaml 기반)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--print", action="store_true", help="명령만 출력")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("calibrate")
    sub.add_parser("calibrate-leader")
    sub.add_parser("teleop")
    rec = sub.add_parser("record")
    rec.add_argument("skill")
    rec.add_argument("--repo-id", required=True)
    rec.add_argument("--episodes", type=int, default=None)
    rec.add_argument("--episode-time", type=float, default=None)
    rec.add_argument("--reset-time", type=float, default=10)
    rec.add_argument("--resume", action="store_true")
    rec.add_argument("--push", action="store_true")
    ro = sub.add_parser("rollout")
    ro.add_argument("--policy", default=None)
    ro.add_argument("--task", default="")
    ro.add_argument("--duration", type=float, default=0)
    ro.add_argument("--interactive", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> None:
    ns = parser().parse_args(argv)
    cfg = load_config(ns.config)
    module, args = build(cfg, ns)
    if ns.print:
        print("python -m", module, " ".join(shlex.quote(a) for a in args))
        return
    patch_bus_timeout(int(cfg["robot"].get("bus_timeout_ms", 50)))
    import importlib

    mod = importlib.import_module(module)
    sys.argv = [module] + args
    mod.main()


if __name__ == "__main__":
    main()
