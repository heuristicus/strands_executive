#!/usr/bin/env python

import rospy
from task_executor.utils import TestTaskAction

if __name__ == '__main__':
    rospy.init_node('test_task_action')
    action_duration = rospy.Duration(60)    
    drive_duration = rospy.Duration(60)    
    action_server = TestTaskAction(expected_action_duration=action_duration, expected_drive_duration=drive_duration)
    action_server.start()
    rospy.spin()
