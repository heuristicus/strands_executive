from __future__ import with_statement 

import rospy
import unittest
import rostest
import random
import threading

import actionlib
from strands_executive_msgs.msg import Task
from task_executor.msg import *
from Queue import Queue
from random import randrange
from mongodb_store.message_store import MessageStoreProxy
from geometry_msgs.msg import Pose, Point, Quaternion
from strands_executive_msgs import task_utils
from strands_executive_msgs.msg import Task
from strands_executive_msgs.srv import AddTasks, SetExecutionStatus
from topological_navigation.msg import GotoNodeAction
from strands_navigation_msgs.msg import TopologicalMap

class FakeActionServer(object):
    def __init__(self, action_string, action_sleep, master, tester):
        self.master = master
        self.tester = tester
        self.action_string = action_string
        self.action_sleep = action_sleep
        self.server = actionlib.SimpleActionServer(action_string, TestExecutionAction, self.execute, False)
        self.server.start() 

    def execute(self, goal):
        # print 'called with goal %s'%goal
        rospy.sleep(self.action_sleep)

        # print 'after sleep'
        with self.master.state_lock:

            for i in range(len(self.master.task_descriptions)):
                task_description = self.master.task_descriptions[i]

                # print task_description[0], task_description[1], task_description[2], task_description[3]
                # print self.master.node_id , self.action_string , goal.some_goal_string , goal.test_pose 
                # task_description[0] == self.master.node_id and 
                if task_description[1] == self.action_string and task_description[2] == goal.some_goal_string and task_description[3] == goal.test_pose: 
                    print 'done task ', self.action_string, goal.some_goal_string

                    # this this was a time value
                    if goal.a_float > 1400000000:
                        self.master.time_diffs.append(rospy.get_rostime().to_sec() - goal.a_float)

                    del self.master.task_descriptions[i]


                    self.server.set_succeeded()
                    return

            


        self.server.set_aborted()




class TaskTester(object):
    def __init__(self, action_types, action_prefix, task_descriptions, action_sleep, tester):        
        self.tester = tester
        self.action_sleep = action_sleep
        # self.node_id = ''
        self.task_descriptions = task_descriptions
        self.time_diffs = []
        self.action_servers = [FakeActionServer(action_prefix + str(n), action_sleep, self, tester) for n in range(action_types)]
        self.state_lock = threading.Lock()
    
    def wait_for_completion(self, wait_duration):
        # give everything time to complete
        start = rospy.get_rostime()
        end = start + wait_duration
        while not rospy.is_shutdown() and rospy.get_rostime() < end:
            with self.state_lock:
                if len(self.task_descriptions) == 0:
                    return 
            rospy.sleep(1)


class TestEntry(object):
    def __init__(self, name, *args):         
        super(TestEntry, self).__init__(*args)    
        rospy.init_node(name)
        self.node_names = []
        rospy.Subscriber('topological_map', TopologicalMap, self.map_callback)

    
    def map_callback(self, msg):        
        print 'got map'
        self.node_names = [node.name for node in msg.nodes]
        
    def get_nodes(self):
        while len(self.node_names) == 0:
            print 'no nodes'
            rospy.sleep(1)
        return self.node_names

    def run_test(self, task_descriptions_fn, test_tasks = 20, time_critical_tasks = 0, time_diffs_fn = None):   
        waypoints = self.get_nodes()
        action_types = 5
        action_sleep = rospy.Duration.from_sec(2)
        action_prefix = 'test_task_'

        msg_store = MessageStoreProxy() 

        task_descriptions = []
        # list comprehension seemed to use the same result from randrange

        start_delay = rospy.Duration(8)

        task_start = rospy.get_rostime() + start_delay
        task_window_size = action_sleep + action_sleep + rospy.Duration(10000)

        for n in range(test_tasks):
            string = 'oh what a lovely number %s is' % n
            pose = Pose(Point(n, 1, 2), Quaternion(3, 4,  5, 6))        
            task_descriptions += [[random.choice(waypoints), 
                action_prefix + str(randrange(action_types)),
                string,
                pose, n, n + 0.1, task_start, task_start + task_window_size]]
            task_start += action_sleep
        assert test_tasks == len(task_descriptions)

        
        time_critical_step = rospy.Duration(360) 
        time_critical_start = rospy.get_rostime() + start_delay + rospy.Duration(120) 

        for n in range(test_tasks, test_tasks + time_critical_tasks):            
            string = 'Please run me at %s is' % time_critical_start.to_sec()
            pose = Pose(Point(n, 1, 2), Quaternion(3, 4,  5, 6))        
            task_descriptions += [[random.choice(waypoints), 
                action_prefix + str(randrange(action_types)),
                string,
                pose, n, time_critical_start.to_sec(), time_critical_start, time_critical_start]]
            time_critical_start += time_critical_step
 
        task_tester = TaskTester(action_types, action_prefix, task_descriptions, action_sleep, self)    

        # get task services
        add_task_srv_name = 'task_executor/add_tasks'
        set_exe_stat_srv_name = 'task_executor/set_execution_status'
        rospy.loginfo("Waiting for task_executor service...")
        rospy.wait_for_service(add_task_srv_name)
        rospy.wait_for_service(set_exe_stat_srv_name)
        rospy.loginfo("Done")        
        add_tasks_srv = rospy.ServiceProxy(add_task_srv_name, AddTasks)
        set_execution_status = rospy.ServiceProxy(set_exe_stat_srv_name, SetExecutionStatus)

        try:
                
            tasks = []
            for task_description in task_descriptions:    
                # create the task from the description
                task = Task(start_node_id=task_description[0], action=task_description[1])        
                # add some dummy arguments
                task_utils.add_string_argument(task, task_description[2])
                task_utils.add_object_id_argument(task, msg_store.insert(task_description[3]), Pose)
                task_utils.add_int_argument(task, task_description[4])
                task_utils.add_float_argument(task, task_description[5])
                task.start_after = task_description[6]
                task.end_before = task_description[7]
                task.max_duration = action_sleep + action_sleep 
                tasks.append(task)
                # print task

            add_tasks_srv(tasks)    
            
            # Start the task executor running
            set_execution_status(True)

            max_wait_duration = start_delay 
            if time_critical_tasks > 0:
                max_wait_duration += time_critical_start - rospy.get_rostime()

            max_travel = rospy.Duration(90)
            for n in range(test_tasks):
                max_wait_duration += (action_sleep + max_travel)

            task_tester.wait_for_completion(max_wait_duration)

            with task_tester.state_lock:

                if task_descriptions_fn is not None:
                    task_descriptions_fn(task_tester.task_descriptions)

                if time_critical_tasks > 0 and time_diffs_fn is not None:
                    time_diffs_fn(task_tester.time_diffs)                

        except rospy.ServiceException, e:
            print "Service call failed: %s"%e
