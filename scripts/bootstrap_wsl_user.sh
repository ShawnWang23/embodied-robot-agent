#!/usr/bin/env bash
set -eo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root inside WSL." >&2
  exit 1
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
user_name="${1:-robotagent}"

if ! id "${user_name}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${user_name}"
fi
usermod --append --groups sudo "${user_name}"

install -m 0644 "${project_root}/config/wsl.conf" /etc/wsl.conf
install -m 0644 "${project_root}/config/robot_agent_ros2.sh" \
  /etc/profile.d/robot_agent_ros2.sh

user_home="$(getent passwd "${user_name}" | cut -d: -f6)"
install -d -o "${user_name}" -g "${user_name}" \
  "${user_home}/.config/robot_agent" \
  "${user_home}/robot_agent_ws/src"
install -m 0644 -o "${user_name}" -g "${user_name}" \
  "${project_root}/config/cyclonedds_localhost.xml" \
  "${user_home}/.config/robot_agent/cyclonedds_localhost.xml"
install -m 0644 -o "${user_name}" -g "${user_name}" \
  "${project_root}/config/use_ros2_localhost.sh" \
  "${user_home}/.config/robot_agent/use_ros2_localhost.sh"

echo "Configured WSL user ${user_name} with workspace ${user_home}/robot_agent_ws."
