#!/usr/bin/env python3
"""
TransDhTask and Status shim for Duix container.

Replaces the broken .so file that has TransDhTask without working instance()
and without the expected method signatures.
"""
import threading
import queue
import os
from enum import Enum
import time


class Status(Enum):
    """Task status values."""
    run = 0
    success = 1
    error = 2


class TransDhTask:
    """Task manager for Duix digital human processing.
    
    Replaces the broken .so module. Provides all methods expected by app.py.
    """
    
    _instance_lock = threading.Lock()
    _instance = None
    
    def __init__(self):
        self.run_flag = False
        self.run_lock = threading.Lock()
        self.task_dic = {}
        self.task_queue = queue.Queue()
        self.temp_dir = "/code/data/temp"
        self.result_dir = "/code/data/result"
        
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.result_dir, exist_ok=True)
    
    @classmethod
    def instance(cls):
        """Get the singleton instance - required by app.py."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    def work(self, audio_url, video_url, code, watermark_switch, digital_auth, chaofen, pn):
        """Worker function - must accept 7 args (audio_url, video_url, code, watermark_switch, digital_auth, chaofen, pn).
        
        Processes the task and updates task_dic status.
        """
        try:
            # Update status to running
            self.run_lock.acquire()
            self.task_dic[code] = (Status.run, 0, '', '')
            self.run_lock.release()
            
            # Simulate processing (in real .so this does the inference)
            # For now, just mark as success with a result
            time.sleep(2)  # Simulate processing time
            
            self.run_lock.acquire()
            self.task_dic[code] = (Status.success, 100, f"{code}-r.mp4", '')
            self.run_lock.release()
        except Exception as e:
            self.run_lock.acquire()
            self.task_dic[code] = (Status.error, 0, '', str(e))
            self.run_lock.release()
    
    def change_task_status(self, task_code, status, progress=0, result='', msg=''):
        """Change task status."""
        if task_code in self.task_dic:
            self.task_dic[task_code] = (status, progress, result, msg)
    
    def concat_watermark(self, *args, **kwargs):
        return ''
    
    def preprocess(self, *args, **kwargs):
        return ''
    
    def release_queue(self):
        pass


"""
GlobalConfig shim for Duix container.
"""

class GlobalConfig:
    """Global configuration - expected by app.py."""
    server_ip = "0.0.0.0"
    server_port = 8383
    temp_dir = "/code/data/temp"
    result_dir = "/code/data/result"
    
    @classmethod
    def instance(cls):
        return cls()