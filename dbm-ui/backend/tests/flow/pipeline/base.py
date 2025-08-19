# -*- coding: utf-8 -*-
"""
TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at https://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""
import uuid
from typing import Any, Dict, List, Type
from unittest.mock import patch

from django.test import TestCase

from backend.tests.mock_data.components.engine_run_pipeline import EngineApiMock


class BasePipelineTest(TestCase):
    """
    流程测试基类
    提供通用的测试方法和工具
    """

    @classmethod
    def setup_class(cls):
        """测试类初始化"""
        pass

    def setUp(self):
        """每个测试方法执行前的设置"""
        # 生成唯一的测试ID
        self.root_id = uuid.uuid4().hex[:24]

    def execute_pipeline_test(
        self,
        flow_class: Type,
        flow_method: str,
        mock_data: Dict[str, Any] = None,
        additional_params: Dict[str, Any] = None,
        additional_mocks: List[Dict[str, Any]] = None,
        expect_failure: bool = False,
        expected_error_message: str = None,
    ) -> Any:
        """
        执行流程测试

        Args:
            flow_class: 流程类
            flow_method: 要测试的流程方法名称
            mock_data: 自定义参数，会覆盖默认参数
            additional_params: 额外需要的参数
            additional_mocks: 额外需要模拟的模块和方法
            expect_failure: 是否期望Pipeline验证失败
            expected_error_message: 期望的错误消息，如果expect_failure为True，则可以指定期望的错误消息

        Returns:
            Any: 流程方法的返回值
        """

        # 创建流程实例
        flow_instance = flow_class(root_id=self.root_id, data=mock_data, **(additional_params or {}))

        # 重置EngineApiMock的状态
        EngineApiMock.was_called = False
        EngineApiMock.last_result = None
        EngineApiMock.last_exception = None

        # 准备所有需要模拟的对象
        patchers = []

        # 添加默认的pipeline mock
        patchers.append(patch("bamboo_engine.api.run_pipeline", side_effect=EngineApiMock.run_pipeline))

        # 添加额外的模拟对象
        if additional_mocks:
            for mock_config in additional_mocks:
                target = mock_config.get("target")
                side_effect = mock_config.get("side_effect")
                return_value = mock_config.get("return_value")

                if side_effect:
                    patchers.append(patch(target, side_effect=side_effect))
                elif return_value is not None:
                    patchers.append(patch(target, return_value=return_value))
                else:
                    # 如果没有指定side_effect或return_value，则使用MagicMock
                    from unittest.mock import MagicMock

                    patchers.append(patch(target, new=MagicMock()))

        # 启动所有patchers
        [patcher.start() for patcher in patchers]

        try:
            # 获取要测试的方法
            flow_method_to_test = getattr(flow_instance, flow_method)

            # 执行流程方法（可能返回None，即使成功）
            result = flow_method_to_test()

            # 检查EngineApiMock是否被调用
            self.assertTrue(EngineApiMock.was_called, "Pipeline engine should be called")

            # 验证执行结果
            if expect_failure:
                self.assertFalse(EngineApiMock.last_result.result, "Pipeline validation should fail")
                if expected_error_message:
                    self.assertIn(
                        expected_error_message,
                        EngineApiMock.last_result.message,
                        f"Expected error message '{expected_error_message}' not found in actual message: "
                        f"'{EngineApiMock.last_result.message}'",
                    )
            else:
                self.assertTrue(
                    EngineApiMock.last_result.result,
                    f"Pipeline validation should pass, but failed with message: "
                    f"{EngineApiMock.last_result.message}",
                )

            return result

        except Exception as e:
            if expect_failure:
                if expected_error_message:
                    self.assertIn(
                        expected_error_message,
                        str(e),
                        f"Expected error message '{expected_error_message}' not found in actual exception: '{str(e)}'",
                    )
                return None
            else:
                raise
        finally:
            # 停止所有patchers
            for patcher in patchers:
                patcher.stop()
