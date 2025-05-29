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
from typing import Dict, Optional

from backend.flow.engine.bamboo.scene.common.machine_os_init import ImportResourceInitStepFlow


class BaseController:
    """
    场景流程控制器基类
    """

    def __init__(self, root_id: str, ticket_data: Optional[Dict] = None):
        self.root_id = root_id
        self.ticket_data = ticket_data

    def fake_scene(self):
        """
        这个scene什么都不做，
        为了给未实现的scene占位或者创建假单据提供给前端测试
        """
        pass

    def import_resource_init_step(self):
        flow = ImportResourceInitStepFlow(root_id=self.root_id, data=self.ticket_data)
        flow.machine_init_flow()

    def machine_recycle_flow(self):
        flow = ImportResourceInitStepFlow(root_id=self.root_id, data=self.ticket_data)
        flow.machine_recycle_flow()

    def machine_idle_check_flow(self):
        flow = ImportResourceInitStepFlow(root_id=self.root_id, data=self.ticket_data)
        flow.machine_idle_check_flow()
