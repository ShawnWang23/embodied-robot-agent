#!/usr/bin/env bash
set -eo pipefail

source "${HOME}/.config/robot_agent/use_ros2_localhost.sh"
set -u

test_dir="$(mktemp -d)"
launch_pid=""
cleanup() {
  if [[ -n "${launch_pid}" ]]; then
    # The launch tree may create several process groups (server, GUI, bridge).
    # It runs in a dedicated session so every descendant can be reaped safely.
    pkill -TERM -s "${launch_pid}" 2>/dev/null || true
    sleep 2
    pkill -KILL -s "${launch_pid}" 2>/dev/null || true
    wait "${launch_pid}" 2>/dev/null || true
  fi
  rm -rf -- "${test_dir}"
}
trap cleanup EXIT

echo "[graphics]"
glxinfo -B | grep -E 'Device:|Accelerated:|OpenGL renderer string:'

echo "[launch TurtleBot3 world]"
setsid timeout --kill-after=5s 40s \
  ros2 launch nav2_bringup tb3_simulation_launch.py \
    headless:=True use_rviz:=False use_composition:=False autostart:=False \
  >"${test_dir}/simulation.log" 2>&1 &
launch_pid="$!"

ready=false
for _ in $(seq 1 25); do
  if ! kill -0 "${launch_pid}" 2>/dev/null; then
    break
  fi
  topics="$(ros2 topic list 2>/dev/null || true)"
  if grep -qx '/scan' <<<"${topics}" && grep -qx '/odom' <<<"${topics}"; then
    ready=true
    break
  fi
  sleep 1
done

if [[ "${ready}" != true ]]; then
  tail -n 100 "${test_dir}/simulation.log"
  echo "TurtleBot3 simulation did not expose /scan and /odom in time." >&2
  exit 1
fi

echo "nodes:"
ros2 node list | sort
echo "required_topics:"
ros2 topic list | grep -E '^/(cmd_vel|joint_states|odom|scan|tf)$' | sort

if ! timeout 8s ros2 topic echo /odom --once \
  >"${test_dir}/odom.log" 2>&1; then
  cat "${test_dir}/odom.log"
  tail -n 100 "${test_dir}/simulation.log"
  echo "No odometry sample was received." >&2
  exit 1
fi

sed -n '1,14p' "${test_dir}/odom.log"
echo "TurtleBot3 Gazebo validation passed."
