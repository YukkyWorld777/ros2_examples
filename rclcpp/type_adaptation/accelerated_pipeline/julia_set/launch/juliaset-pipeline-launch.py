# Copyright 2021 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Launch the GPU pipeline."""

import platform

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition, LaunchConfigurationEquals
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode
from numpy import float

RESOLUTIONS = {'16K': (15360, 8640),
               '8K': (7680, 4320),
               '4K': (3840, 2160),
               '1080p': (1920, 1080),
               '720p': (1280, 720),
               '480p': (852, 480)}
IMAGE_HZ = 100.0

# IMAGE_PROC_COUNT = 3
MAX_ITERATION = 50

JULIASET_PARAMS = [{'min_x_range': -2.5},
                   {'max_x_range': 2.5},
                   {'min_y_range': -1.5},
                   {'max_y_range': 1.5},
                   {'start_x': 0.7885},
                   {'start_y': 0.7885},
                   {'boundary_radius': 25.0},
                   {'max_iterations': float(MAX_ITERATION)}]

launch_args = [DeclareLaunchArgument('config', default_value='composite',
                                     description='Graph configuration (pipeline|composite)'),
               DeclareLaunchArgument('resolution', default_value='1080p',
                                     description='Resolution key (16K|8K|4K|1080p|720p|480p)'),
               DeclareLaunchArgument('enable_mt', default_value='false',
                                     description='Enable multithreaded composable containers'),
               DeclareLaunchArgument('enable_nsys', default_value='false',
                                     description='Enable nsys profiling'),
               DeclareLaunchArgument('nsys_profile_label', default_value='',
                                     description='Label to append for nsys profile output'),
               DeclareLaunchArgument('nsys_profile_flags', default_value='--trace=osrt,nvtx,cuda',
                                     description='Flags for nsys profile')
               ]


def generate_launch_description():
    """Generate launch description with cam2image feeding N JuliasetNode pipeline."""
    ld = LaunchDescription(launch_args)
    ld.add_action(OpaqueFunction(function=launch_setup))
    return ld


def launch_setup(context):
    config = LaunchConfiguration('config').perform(context)
    resolution = LaunchConfiguration('resolution').perform(context)
    enable_mt = IfCondition(LaunchConfiguration(
        'enable_mt')).evaluate(context)
    enable_nsys = IfCondition(LaunchConfiguration(
        'enable_nsys')).evaluate(context)
    nsys_profile_label = LaunchConfiguration(
        'nsys_profile_label').perform(context)
    nsys_profile_flags = LaunchConfiguration(
        'nsys_profile_flags').perform(context)

    container_prefix = ''
    # container_prefix = 'cuda-gdb -ex run --args'

    if enable_nsys:
        nsys_profile_name = build_profile_name(nsys_profile_label, config, enable_mt, resolution)
        container_prefix = f'nsys profile {nsys_profile_flags} -o {nsys_profile_name}'

    cam2image_node = ComposableNode(package='image_tools',
                                    name='cam2image',
                                    plugin='image_tools::Cam2Image',
                                    remappings=[('/image', '/image_in')],
                                    extra_arguments=[
                                        {'use_intra_process_comms': True}],
                                    parameters=[{'burger_mode': True,
                                                 'history': 'keep_last',
                                                 'frequency': IMAGE_HZ,
                                                 'width': RESOLUTIONS[resolution][0],
                                                 'height': RESOLUTIONS[resolution][1]}])
    # composite
    composite_node = ComposableNode(
        package='julia_set_example',
        plugin='type_adapt_example::JuliasetNode',
        name='juliaset_node',
        parameters=[{'is_composite': True}] + JULIASET_PARAMS,
        remappings=[('/image_out', '/composite/image_out')])

    composite_container = ComposableNodeContainer(
        name='container',
        namespace='',
        package='rclcpp_components',
        executable='component_container' + ('_mt' if enable_mt else ''),
        composable_node_descriptions=[cam2image_node, composite_node],
        prefix=container_prefix,
        sigkill_timeout='500' if enable_nsys else '5',
        sigterm_timeout='500' if enable_nsys else '5',
        output='both',
        condition=LaunchConfigurationEquals('config', 'composite')
    )

    # pipeline
    pipeline_nodes = [cam2image_node]

    pipeline_nodes.append(ComposableNode(
        package='julia_set_example',
        plugin='type_adapt_example::MapNode',
        name='map_node',
        parameters=JULIASET_PARAMS,
        remappings=[('/image_out', '/image_out0')]))

    for i in range(1, MAX_ITERATION):
        pipeline_nodes.append(ComposableNode(
            package='julia_set_example',
            plugin='type_adapt_example::JuliasetNode',
            name='juliaset_node%d' % (i),
            parameters=[{'is_composite': False}, {'proc_id': i}] + JULIASET_PARAMS,
            remappings=[('/image_in', '/image_out%d' % (i - 1)),
                        ('/image_out', '/image_out%d' % (i))]))

    pipeline_nodes.append(ComposableNode(
        package='julia_set_example',
        plugin='type_adapt_example::ColorizeNode',
        name='colorize_node',
        parameters=[{'max_iterations': float(MAX_ITERATION)}] + JULIASET_PARAMS,
        remappings=[('/image_in', '/image_out%d' % (MAX_ITERATION - 1)),
                    ('/image_out', '/pipeline/image_out')]))

    pipeline_container = ComposableNodeContainer(
        name='pipeline_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container' + ('_mt' if enable_mt else ''),
        prefix=container_prefix,
        sigkill_timeout='500' if enable_nsys else '5',
        sigterm_timeout='500' if enable_nsys else '5',
        composable_node_descriptions=pipeline_nodes,
        output='both',
        condition=LaunchConfigurationEquals('config', 'pipeline')
    )

    return [pipeline_container, composite_container]


def build_profile_name(label, config, enable_mt, resolution):
    return f"ros-type_adapt-{platform.machine()}{'' if not enable_mt else '-mt'}-{config}-{resolution}-{int(IMAGE_HZ)}hz{'' if not label else '-' + label}"
