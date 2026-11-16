#!/usr/bin/env bash
set -eo pipefail

# The generated ROS setup script reads optional variables before defining them,
# so enable nounset only after the environment has been loaded.
source /opt/ros/jazzy/setup.bash
set -u

# This smoke test runs both nodes inside one WSL distro. Restrict discovery to
# the host so Windows mirrored-network interfaces cannot confuse DDS discovery.
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface address="127.0.0.1"/></Interfaces></General></Domain></CycloneDDS>'

echo "[environment]"
printf 'ROS_DISTRO=%s\n' "${ROS_DISTRO:-missing}"
python3 --version
printf 'ros2=%s\n' "$(command -v ros2)"
printf 'colcon=%s\n' "$(command -v colcon)"
dpkg-query -W ros-jazzy-desktop ros-dev-tools
package_audit="$(dpkg --audit)"
if [[ -n "${package_audit}" ]]; then
  printf '%s\n' "${package_audit}"
  echo "dpkg reported incomplete package state." >&2
  exit 1
fi

echo "[topic communication]"
test_dir="$(mktemp -d)"
talker_pid=""
cleanup() {
  if [[ -n "${talker_pid}" ]]; then
    kill "${talker_pid}" 2>/dev/null || true
    wait "${talker_pid}" 2>/dev/null || true
  fi
  rm -rf -- "${test_dir}"
}
trap cleanup EXIT

timeout 10s ros2 run demo_nodes_cpp talker >"${test_dir}/talker.log" 2>&1 &
talker_pid="$!"
sleep 2
echo "discovered_nodes:"
ros2 node list || true
echo "discovered_topics:"
ros2 topic list || true
set +e
timeout 6s stdbuf -oL ros2 run demo_nodes_cpp listener \
  >"${test_dir}/listener.log" 2>&1
listener_status="$?"
set -e

if [[ "${listener_status}" -ne 0 && "${listener_status}" -ne 124 ]]; then
  cat "${test_dir}/listener.log"
  echo "Listener exited unexpectedly with status ${listener_status}." >&2
  exit "${listener_status}"
fi

received_count="$(grep -c 'I heard:' "${test_dir}/listener.log" || true)"
if [[ "${received_count}" -lt 2 ]]; then
  cat "${test_dir}/talker.log"
  cat "${test_dir}/listener.log"
  echo "Expected at least 2 received topic messages; got ${received_count}." >&2
  exit 1
fi

sed -n '1,4p' "${test_dir}/listener.log"
printf 'received_messages=%s\n' "${received_count}"
echo "ROS 2 validation passed."
