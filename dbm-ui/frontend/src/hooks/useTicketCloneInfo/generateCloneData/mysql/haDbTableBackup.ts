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
import TicketModel, { type Mysql } from '@services/model/ticket/ticket';

import { ClusterTypes } from '@common/const';

import { random } from '@utils';

// Mysql 库表备份
export function generateMysqlDbTableBackupCloneData(ticketData: TicketModel<Mysql.HaDBTableBackup>) {
  const { clusters, infos } = ticketData.details;
  const tableDataList = infos.map((item) => ({
    backupLocal: item.backup_on || clusters[item.cluster_id].cluster_type === ClusterTypes.TENDBHA ? 'Slave' : 'Master',
    clusterData: {
      domain: clusters[item.cluster_id].immute_domain,
      id: item.cluster_id,
    },
    dbPatterns: item.db_patterns,
    ignoreDbs: item.ignore_dbs,
    ignoreTables: item.ignore_tables,
    rowKey: random(),
    tablePatterns: item.table_patterns,
  }));
  return Promise.resolve({
    remark: ticketData.remark,
    tableDataList,
  });
}
