#!/usr/bin/env python3
"""
Convert a ROS1 nav_msgs/Odometry topic to a TUM trajectory file.

TUM format (no header lines):
timestamp tx ty tz qx qy qz qw

Usage:
  rosrun your_pkg odom_to_tum.py --topic /lio_sam/mapping/odometry --out /tmp/est.tum
"""

import argparse
import os
import signal
import sys
import math
import rospy
from nav_msgs.msg import Odometry

class OdomToTUM:
    def __init__(self, topic, out_path, precision=9):
        self.topic = topic
        self.out_path = out_path
        self.precision = precision
        self._f = None
        self._last_stamp = None
        self._msg_count = 0

    def _open(self):
        odir = os.path.dirname(self.out_path)
        if odir and not os.path.exists(odir):
            os.makedirs(odir)
        # line-buffered text
        self._f = open(self.out_path, "w", buffering=1)

    def _close(self):
        if self._f:
            self._f.flush()
            self._f.close()
            self._f = None

    def shutdown(self):
        rospy.loginfo("Shutting down, wrote %d poses to %s", self._msg_count, self.out_path)
        self._close()

    def _quat_norm_ok(self, x, y, z, w, eps=1e-3):
        n = math.sqrt(x*x + y*y + z*z + w*w)
        return abs(n - 1.0) < eps or n == 0.0

    def cb(self, msg: Odometry):
        # timestamp in seconds (float). evo expects seconds (can be absolute or relative).
        ts = msg.header.stamp.to_sec()
        if ts == 0.0:
            # sometimes messages can be 0 before sim_time is ready
            return

        # ensure temporal monotonicity (drop exact duplicates)
        if self._last_stamp is not None and ts < self._last_stamp:
            # Messages out of order can happen; evo can sort, but we keep the log monotonic by skipping older ones
            return
        if self._last_stamp is not None and ts == self._last_stamp:
            return

        p = msg.pose.pose.position
        q = msg.pose.pose.orientation

        if not self._quat_norm_ok(q.x, q.y, q.z, q.w):
            # not fatal, but worth noting
            rospy.logwarn_throttle(2.0, "Quaternion not normalized (|q|!=1). Writing as-is.")

        line = f"{ts:.{self.precision}f} {p.x:.9f} {p.y:.9f} {p.z:.9f} {q.x:.9f} {q.y:.9f} {q.z:.9f} {q.w:.9f}\n"
        self._f.write(line)
        self._msg_count += 1
        self._last_stamp = ts

def main():
    parser = argparse.ArgumentParser(description="Convert Odometry topic to TUM file")
    parser.add_argument("--topic", default="/lio_sam/mapping/odometry", help="Odometry topic (nav_msgs/Odometry)")
    parser.add_argument("--out", required=True, help="Output TUM path (e.g., /tmp/est.tum)")
    parser.add_argument("--precision", type=int, default=9, help="Timestamp decimal precision (default: 9)")
    args, _ = parser.parse_known_args()

    rospy.init_node("odom_to_tum", anonymous=True)
    conv = OdomToTUM(args.topic, args.out, args.precision)
    conv._open()

    # graceful shutdown on SIGINT/SIGTERM
    def _sig_handler(signum, frame):
        rospy.signal_shutdown(f"signal {signum}")
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    rospy.Subscriber(args.topic, Odometry, conv.cb, queue_size=100, tcp_nodelay=True)
    rospy.loginfo("Listening on %s, writing to %s (TUM format)", args.topic, args.out)

    try:
        rospy.spin()
    finally:
        conv.shutdown()

if __name__ == "__main__":
    sys.exit(main())
