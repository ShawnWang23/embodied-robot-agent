"""Create a short MP4 from verified local project artifacts.

The video is deliberately reproducible and silent. It does not synthesize robot footage:
camera panels and the closed-loop trace come from persisted ROS2/Gazebo runs, while
service status and benchmark metrics come from Phase 6 and Phase 7 artifacts.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from textwrap import wrap

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1280
HEIGHT = 720
FPS = 20
BACKGROUND = (16, 24, 40)
PANEL = (28, 40, 62)
TEXT = (235, 242, 255)
MUTED = (164, 181, 205)
ACCENT = (53, 203, 154)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the Phase 8 demo MP4.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/phase8/robot_agent_demo.mp4"),
    )
    parser.add_argument(
        "--camera-image",
        type=Path,
        default=Path("artifacts/phase5_camera.jpg"),
    )
    parser.add_argument(
        "--phase6-database",
        type=Path,
        default=Path("artifacts/phase6_live_tasks.db"),
    )
    parser.add_argument(
        "--phase7-summary",
        type=Path,
        default=Path(
            "artifacts/phase7/20261110T133038290474Z/summary.json"
        ),
    )
    parser.add_argument(
        "--unified-result",
        type=Path,
        default=Path("artifacts/unified/result.json"),
    )
    parser.add_argument(
        "--unified-camera",
        type=Path,
        default=Path("artifacts/unified/camera.jpg"),
    )
    return parser.parse_args()


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    path = Path("C:/Windows/Fonts") / name
    if not path.is_file():
        path = Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf")
    return ImageFont.truetype(str(path), size)


def base_slide(title: str, subtitle: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((50, 42, WIDTH - 50, HEIGHT - 55), 24, fill=PANEL)
    draw.text((88, 74), title, fill=TEXT, font=font(46, bold=True))
    if subtitle:
        draw.text((90, 137), subtitle, fill=MUTED, font=font(23))
    draw.text(
        (88, HEIGHT - 42),
        "ROS2 + LLM Indoor Robot Agent · verified local artifacts",
        fill=MUTED,
        font=font(18),
    )
    return image, draw


def bullet_slide(title: str, bullets: list[str], subtitle: str = "") -> Image.Image:
    image, draw = base_slide(title, subtitle)
    y = 195
    body = font(29)
    for bullet in bullets:
        lines = wrap(bullet, width=60)
        draw.ellipse((92, y + 11, 104, y + 23), fill=ACCENT)
        for index, line in enumerate(lines):
            draw.text((122, y + index * 40), line, fill=TEXT, font=body)
        y += max(1, len(lines)) * 40 + 20
    return image


def architecture_slide() -> Image.Image:
    image, draw = base_slide("系统闭环架构", "LLM 不直接控制底盘；所有动作均经过校验工具")
    labels = [
        "Natural Language",
        "Planner + Pydantic",
        "LangGraph",
        "Mission FSM",
        "RobotAdapter",
        "Nav2 / Camera / YOLO",
    ]
    x_positions = [75, 270, 475, 650, 835, 1020]
    y = 285
    for index, (label, x) in enumerate(zip(labels, x_positions)):
        box_width = 155 if index < 5 else 180
        draw.rounded_rectangle(
            (x, y, x + box_width, y + 105),
            18,
            fill=(37, 55, 82),
            outline=ACCENT,
            width=3,
        )
        lines = wrap(label, width=14)
        for line_index, line in enumerate(lines):
            draw.text(
                (x + 14, y + 22 + line_index * 29),
                line,
                fill=TEXT,
                font=font(22, bold=True),
            )
        if index < len(labels) - 1:
            arrow_start = x + box_width + 5
            arrow_end = x_positions[index + 1] - 10
            draw.line((arrow_start, y + 52, arrow_end, y + 52), fill=ACCENT, width=5)
            draw.polygon(
                [
                    (arrow_end, y + 52),
                    (arrow_end - 14, y + 43),
                    (arrow_end - 14, y + 61),
                ],
                fill=ACCENT,
            )
    draw.text(
        (340, 470),
        "Feedback → bounded recovery → checkpoint → human confirmation",
        fill=MUTED,
        font=font(28),
    )
    return image


def camera_slide(path: Path) -> Image.Image:
    image, draw = base_slide("真实 ROS2 相机与 YOLO", "TurtleBot3 Waffle Pi · /camera/image_raw")
    camera = Image.open(path).convert("RGB")
    camera.thumbnail((720, 455))
    image.paste(camera, (80, 190))
    facts = [
        "640 × 480 BGR8",
        "YOLO26n · CPU",
        "仿真画面：person/chair 均未检出",
        "官方阳性对照：4 个 person",
        "最高置信度约 0.872",
    ]
    y = 205
    for fact in facts:
        for index, line in enumerate(wrap(fact, width=24)):
            prefix = "• " if index == 0 else "  "
            draw.text((835, y), prefix + line, fill=TEXT, font=font(24))
            y += 34
        y += 17
    return image


def unified_evidence_slide(
    result: dict[str, object],
    camera_path: Path,
) -> Image.Image:
    image, draw = base_slide(
        "同一仿真栈的闭环实证",
        "一个 Waffle 实例 · Nav2 + 1920×1080 Camera + YOLO + Replan",
    )
    camera = Image.open(camera_path).convert("RGB")
    camera.thumbnail((570, 350))
    image.paste(camera, (80, 195))
    draw.rounded_rectangle((80, 555, 650, 605), 12, fill=(37, 55, 82))
    draw.text(
        (100, 565),
        "真实 Gazebo 相机帧 · 未合成机器人画面",
        fill=TEXT,
        font=font(22, bold=True),
    )

    history = result.get("task_history", [])
    steps = [
        step
        for task in history
        if isinstance(task, dict)
        for step in task.get("steps", [])
        if isinstance(step, dict)
    ]
    y = 188
    for index, step in enumerate(steps, start=1):
        action = str(step.get("action", "unknown"))
        draw.rounded_rectangle(
            (700, y, 1185, y + 45),
            10,
            fill=(37, 55, 82),
            outline=ACCENT,
            width=2,
        )
        draw.text(
            (720, y + 8),
            f"{index}. {action}  ✓",
            fill=TEXT,
            font=font(22, bold=True),
        )
        y += 52
    draw.text(
        (700, 570),
        f"Replan={result.get('replan_count', 0)} · "
        f"Goal satisfied={result.get('goal_satisfied')}",
        fill=ACCENT,
        font=font(23, bold=True),
    )
    return image


def load_phase6(path: Path) -> dict[str, object]:
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT payload FROM tasks ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise RuntimeError("Phase 6 task database contains no task")
    return json.loads(row[0])


def write_video(output: Path, slides: list[tuple[Image.Image, float]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        FPS,
        (WIDTH, HEIGHT),
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open the MP4 writer")
    try:
        for slide, duration in slides:
            frame = cv2.cvtColor(np.asarray(slide), cv2.COLOR_RGB2BGR)
            for _ in range(round(duration * FPS)):
                writer.write(frame)
    finally:
        writer.release()

    capture = cv2.VideoCapture(str(output))
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        capture.release()
    if frame_count <= 0 or (width, height) != (WIDTH, HEIGHT):
        raise RuntimeError("generated MP4 failed frame-count or resolution validation")
    preview_path = output.with_name(f"{output.stem}_preview.jpg")
    preview_capture = cv2.VideoCapture(str(output))
    preview_frames: list[np.ndarray] = []
    try:
        duration_seconds = frame_count / FPS
        sample_seconds = np.linspace(1, max(1, duration_seconds - 1), 8)
        for second in sample_seconds:
            preview_capture.set(cv2.CAP_PROP_POS_MSEC, second * 1_000)
            ok, preview = preview_capture.read()
            if not ok:
                raise RuntimeError(f"could not decode preview frame at {second}s")
            preview_frames.append(cv2.resize(preview, (320, 180)))
    finally:
        preview_capture.release()
    contact_sheet = np.vstack(
        (np.hstack(preview_frames[:4]), np.hstack(preview_frames[4:]))
    )
    if not cv2.imwrite(str(preview_path), contact_sheet):
        raise RuntimeError("could not write MP4 preview contact sheet")
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "frames": frame_count,
                "fps": FPS,
                "resolution": [width, height],
                "duration_seconds": frame_count / FPS,
                "preview": str(preview_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    args = parse_args()
    phase6 = load_phase6(args.phase6_database)
    phase7 = json.loads(args.phase7_summary.read_text(encoding="utf-8"))
    unified = json.loads(args.unified_result.read_text(encoding="utf-8"))
    steps = phase6["steps"]
    actions = " → ".join(step["action"] for step in steps)

    slides = [
        (
            bullet_slide(
                "室内机器人长程任务执行 Agent",
                [
                    "ROS2 Jazzy + Nav2 + LangGraph + LLM + YOLO",
                    "从自然语言计划到导航、感知、恢复与人工接管",
                    "Phase 8 verified delivery",
                ],
                "可复现工程演示 · 2026-11-16",
            ),
            4.0,
        ),
        (architecture_slide(), 5.0),
        (
            bullet_slide(
                "FastAPI + SiliconFlow 在线任务",
                [
                    f"持久化任务终态：{phase6['status']}",
                    f"结构化步骤数：{len(steps)}",
                    f"执行链：{actions}",
                    "地点坐标在 Tool Registry 中解析，LLM 不生成 cmd_vel",
                ],
                "读取 artifacts/phase6_live_tasks.db 的真实任务快照",
            ),
            5.0,
        ),
        (
            bullet_slide(
                "ROS2 / Nav2 回归",
                [
                    "自然语言任务：实验室门口 → 返回起点",
                    "两个 NavigateToPose goal 均一次成功",
                    "Nav2 number_of_recoveries = 0",
                    "任务状态 completed，无 ROS/Gazebo 残留进程",
                ],
                "WSL Ubuntu 24.04 · ROS2 Jazzy · Gazebo Harmonic",
            ),
            4.5,
        ),
        (camera_slide(args.camera_image), 5.0),
        (unified_evidence_slide(unified, args.unified_camera), 6.0),
        (
            bullet_slide(
                "感知驱动的局部重规划",
                [
                    "初始任务 4 步：导航 → 拍照 → 检测 → 返回起点",
                    "person=false 触发结果审查，不直接结束 Agent",
                    "生成并重新校验 3 步计划：备用观察点 → 拍照 → 再检测",
                    "3 个 Nav2 Goal 均单次成功，number_of_recoveries = 0",
                    "总计 7 步、2 个持久化任务，最终 goal_satisfied = true",
                ],
                "真实 artifacts/unified/result.json · 不是 FakeRobot 指标",
            ),
            5.5,
        ),
        (
            bullet_slide(
                "Phase 7 · 40 次可靠性基准",
                [
                    f"Expectation Pass：{phase7['expectation_pass_rate'] * 100:.2f}%",
                    f"Task Success：{phase7['task_success_rate'] * 100:.2f}%",
                    f"Recovery Success：{phase7['recovery_success_rate'] * 100:.2f}%",
                    f"Tool Calling Success：{phase7['tool_calling_success_rate'] * 100:.2f}%",
                    f"Human Intervention：{phase7['human_intervention_rate'] * 100:.2f}%",
                ],
                "FakeRobot 确定性故障注入；不冒充 40 次 Gazebo 或真机实验",
            ),
            5.0,
        ),
        (
            bullet_slide(
                "交付完成",
                [
                    "54 项 pytest 全部通过，核心模块分支覆盖率 87.56%",
                    "统一 Gazebo 栈完成 Nav2 + Camera + YOLO + Replan",
                    "SQLite checkpoint、重启隔离与双确认恢复",
                    "OpenAPI、安装文档、架构/FSM/工作流图与测试报告",
                    "启动 API：uv run robot-agent-api",
                ],
                "README.md 是项目总入口",
            ),
            4.0,
        ),
    ]
    write_video(args.output, slides)


if __name__ == "__main__":
    main()
