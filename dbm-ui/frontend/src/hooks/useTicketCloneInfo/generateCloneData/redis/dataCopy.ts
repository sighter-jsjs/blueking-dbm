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
import TicketModel, { type Redis } from '@services/model/ticket/ticket';

import { random } from '@utils';

// Redis 集群数据复制
export function generateRedisDataCopyCloneData(ticketData: TicketModel<Redis.ClusterDataCopy>) {
  const { clusters, infos } = ticketData.details;

  const tableList = infos.map((item) => ({
    clusterType: item.src_cluster_type,
    excludeKey: item.key_black_regex ? item.key_black_regex.split('\n') : [],
    includeKey: item.key_white_regex ? item.key_white_regex.split('\n') : [],
    isLoading: false,
    password: item.src_cluster_password,
    rowKey: random(),
    srcCluster: clusters[item.src_cluster].immute_domain,
    srcClusterId: item.src_cluster,
    srcClusterTypeName: clusters[item.src_cluster].cluster_type_name,
    targetBusines: item.dst_bk_biz_id,
    targetCluster: clusters[item.dst_cluster].immute_domain,
    targetClusterId: item.dst_cluster,
  }));

  return Promise.resolve({
    copyMode: ticketData.details.dts_copy_type,
    disconnectSetting: ticketData.details.sync_disconnect_setting,
    remark: ticketData.remark,
    tableList,
    writeMode: ticketData.details.write_mode,
  });
}
