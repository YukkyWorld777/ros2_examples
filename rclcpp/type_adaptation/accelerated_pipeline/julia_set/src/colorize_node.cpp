// Copyright 2021 Open Source Robotics Foundation, Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "julia_set/colorize_node.hpp"
#include <memory>
#include <utility>

#include "rclcpp/rclcpp.hpp"
#include "rclcpp_components/register_node_macro.hpp"
#include "sensor_msgs/image_encodings.hpp"
#include "type_adapters/image_container.hpp"

namespace type_adapt_example
{

ColorizeNode::ColorizeNode(rclcpp::NodeOptions options)
: rclcpp::Node("colorize_node", options.use_intra_process_comms(true)),
  is_initialized{false}
{
  RCLCPP_INFO(get_logger(), "Setting up Colorize node");

  juliaset_params_.kMaxIterations = declare_parameter<double>("max_iterations", 50.0);

  // This is the input into the pipeline from an external source
  sub_ =
    create_subscription<type_adapt_example::ImageContainer>(
    "image_in", 1,
    std::bind(&ColorizeNode::ColorizeCallback, this, std::placeholders::_1));

  // This is the publication to the rest of the GPU pipeline
  pub_ = create_publisher<type_adapt_example::ImageContainer>("image_out", 1);
}

void ColorizeNode::ColorizeCallback(
  std::unique_ptr<type_adapt_example::ImageContainer> image)
{
  if (!is_initialized) {
    img_property_.row_step = image->step();
    img_property_.height = image->height();
    img_property_.width = image->width();
    img_property_.encoding = image->encoding();

    // Only support 8 bit encodings (since point cloud can only support each color point with 8 bits)
    if (image->encoding() == sensor_msgs::image_encodings::RGB8) {
      img_property_.red_offset = 0;
      img_property_.green_offset = 1;
      img_property_.blue_offset = 2;
      img_property_.color_step = 3;
    } else if (image->encoding() == sensor_msgs::image_encodings::BGR8) {
      img_property_.blue_offset = 0;
      img_property_.green_offset = 1;
      img_property_.red_offset = 2;
      img_property_.color_step = 3;
    } else if (image->encoding() == sensor_msgs::image_encodings::MONO8) {
      img_property_.red_offset = 0;
      img_property_.green_offset = 0;
      img_property_.blue_offset = 0;
      img_property_.color_step = 1;
    }

    juliaset_handle_ = std::make_unique<Juliaset>(img_property_, juliaset_params_);
    is_initialized = true;
  }

  auto out = std::make_unique<type_adapt_example::ImageContainer>(
    image->header(), image->height(), image->width(), image->encoding(),
    image->step() / sizeof(float), image->cuda_stream());

  juliaset_handle_->colorize(
    out->cuda_mem(), reinterpret_cast<float *>(image->cuda_mem()), out->cuda_stream()->stream());

  pub_->publish(std::move(out));

}

}  // namespace type_adapt_example

RCLCPP_COMPONENTS_REGISTER_NODE(type_adapt_example::ColorizeNode)
