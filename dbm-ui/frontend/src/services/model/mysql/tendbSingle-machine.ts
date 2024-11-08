/*
 * TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
 *
 * Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
 *
 * Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at https://opensource.org/licenses/MIT
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
 * on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for
 * the specific language governing permissions and limitations under the License.
 */

import type { HostInfo, MachineRelatedCluster, MachineRelatedInstance, MachineSpecConfig } from '@services/types';

export default class TendbSingleMachine {
  bk_cloud_id: number;
  bk_cloud_name: string;
  bk_host_id: number;
  cluster_type: string;
  create_at: string;
  host_info: HostInfo;
  instance_role: string;
  ip: string;
  machine_type: string;
  related_clusters: MachineRelatedCluster[];
  related_instances: MachineRelatedInstance[];
  spec_config: MachineSpecConfig;
  spec_id: number;

  constructor(payload = {} as TendbSingleMachine) {
    this.bk_cloud_id = payload.bk_cloud_id;
    this.bk_cloud_name = payload.bk_cloud_name;
    this.bk_host_id = payload.bk_host_id;
    this.cluster_type = payload.cluster_type;
    this.create_at = payload.create_at;
    this.host_info = payload.host_info;
    this.instance_role = payload.instance_role;
    this.ip = payload.ip;
    this.machine_type = payload.machine_type;
    this.related_clusters = payload.related_clusters;
    this.related_instances = payload.related_instances;
    this.spec_config = payload.spec_config;
    this.spec_id = payload.spec_id;
  }
}
