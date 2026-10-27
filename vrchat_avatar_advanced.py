#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VRChat Avatar Advanced Autonomy
- Gesture control
- Gaze tracking
- Emotion mapping
"""

import random
from pythonosc import udp_client

client = udp_client.SimpleUDPClient('127.0.0.1', 9000)

def random_gesture():
    gestures = ['wave', 'nod', 'smile']
    g = random.choice(gestures)
    client.send_message('/avatar/parameters/VRC_Gesture', g)
    print(f'Gesture: {g}')

def gaze_shift():
    x = random.uniform(-1,1)
    y = random.uniform(-1,1)
    client.send_message('/avatar/parameters/VRC_GazeX', x)
    client.send_message('/avatar/parameters/VRC_GazeY', y)

if __name__ == '__main__':
    random_gesture()
    gaze_shift()
