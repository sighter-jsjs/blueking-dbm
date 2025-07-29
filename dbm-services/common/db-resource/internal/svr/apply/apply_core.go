/*
 * TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
 * Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
 * Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at https://opensource.org/licenses/MIT
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
 * an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations under the License.
 */

package apply

import (
	"fmt"
	"sort"
	"strings"

	"dbm-services/common/db-resource/internal/model"
	"dbm-services/common/db-resource/internal/svr/task"
	"dbm-services/common/go-pubpkg/cmutil"
	"dbm-services/common/go-pubpkg/logger"

	mapset "github.com/deckarep/golang-set/v2"
)

const (
	// MINDISTRUTE TODO
	MINDISTRUTE = 20
	// RANDOM TODO
	RANDOM = "RANDOM"
)

type subZone = string

// PickerObject picker object
type PickerObject struct {
	Item           string
	Count          int
	PickDistribute map[string]int
	// 已存在的园区
	ExistSubZone     []subZone
	SatisfiedHostIds []int
	// SelectedResources []*model.TbRpDetail
	// 待选择实例
	// 具备优先级的待选实例列表
	PriorityElements      map[subZone]*PriorityQueue
	SubZonePrioritySumMap map[subZone]int64

	// 资源请求在同园区的时候才生效
	ExistEquipmentIds     []string // 已存在的设备Id
	ExistLinkNetdeviceIds []string // 已存在的网卡Id
	ProcessLogs           []string
}

// LockReturnPickers 将匹配好的机器资源,查询出详情结果返回
//
//	@param elements
//	@return []model.BatchGetTbDetailResult
//	@return error
func LockReturnPickers(elements []*PickerObject, mode string) ([]model.BatchGetTbDetailResult, error) {
	var getter []model.BatchGetTbDetail
	for _, v := range elements {
		getter = append(getter, model.BatchGetTbDetail{
			Item:      v.Item,
			BkHostIds: v.SatisfiedHostIds,
		})
	}
	data, err := model.BatchGetSatisfiedByAssetIds(getter, mode)
	if err != nil {
		logger.Error(fmt.Sprintf("占用机器，更改机器状态失败%s", err.Error()))
	}
	if mode == model.Used {
		sendArchivedTask(data)
	}
	return data, err
}

// sendArchivedTask 归档
//
//	@param data
func sendArchivedTask(data []model.BatchGetTbDetailResult) {
	for _, v := range data {
		for _, l := range v.Data {
			task.ArchivedResourceChan <- l.ID
		}
	}
}

// createNice 创建Nice值
//
//	@param cpu
//	@param mem
//	@param sdd
//	@param hdd
//	@return rs
func createNice(cpu int, mem, sdd, hdd int) (rs int64) {
	rs = int64(cpu*1000000000000 + mem*100000 + sdd + hdd)
	return
}

// AnalysisResource 待选取资源排序
//
//	@param ins
//	@return map
func AnalysisResource(ins []model.TbRpDetail, israndom bool) map[string][]InstanceObject {
	result := make(map[string][]InstanceObject)
	for _, v := range ins {
		linkids := strings.Split(v.NetDeviceID, ",")
		t := InstanceObject{
			BkHostId:        v.BkHostID,
			Equipment:       v.RackID,
			LinkNetdeviceId: linkids,
			Nice:            createNice(int(v.CPUNum), v.DramCap, 0, 0),
			InsDetail:       &v,
		}
		if israndom {
			result[RANDOM] = append(result[RANDOM], t)
		} else {
			result[v.SubZone] = append(result[v.SubZone], t)
		}
	}

	// 对个每个camp里面机器按照规则排序，便于后续picker的时候取最优的
	for key := range result {
		sort.Sort(Wrapper{result[key], func(p, q *InstanceObject) bool {
			return q.Nice > p.Nice // Nice 递减排序
		}})
	}
	return result
}

// NewPicker 初始化资源选择器
//
//	@param count
//	@param item
//	@return *PickerObject
func NewPicker(count int, item string) *PickerObject {
	return &PickerObject{
		Item:                  item,
		Count:                 count,
		ExistEquipmentIds:     make([]string, 0),
		ExistLinkNetdeviceIds: make([]string, 0),
		SatisfiedHostIds:      make([]int, 0),
		PickDistribute:        make(map[string]int),
	}
}

// CrossSwitchCheck 跨交换机检查
func (c *PickerObject) CrossSwitchCheck(v InstanceObject) bool {
	if len(v.LinkNetdeviceId) == 0 {
		return false
	}
	return c.InterSectForLinkNetDevice(v.LinkNetdeviceId) == 0
}

// CrossRackCheck 跨机架检查
func (c *PickerObject) CrossRackCheck(v InstanceObject) bool {
	if cmutil.IsEmpty(v.Equipment) {
		return false
	}
	return c.InterSectForEquipment(v.Equipment) == 0
}

// DebugDistributeLog debug log
func (c *PickerObject) DebugDistributeLog() {
	for key, v := range c.PickDistribute {
		logger.Debug(fmt.Sprintf("Zone:%s,PickCount:%d", key, v))
	}
}

// PreselectedSatisfiedInstance preselect satisfied resource
func (c *PickerObject) PreselectedSatisfiedInstance() error {
	affectRows, err := model.UpdateTbRpDetail(c.SatisfiedHostIds, model.Preselected)
	if err != nil {
		return err
	}
	if int(affectRows) != len(c.SatisfiedHostIds) {
		return fmt.Errorf("update %d qualified resource to preselect,only %d real update status", len(c.SatisfiedHostIds),
			affectRows)
	}
	return nil
}

// RollbackUnusedInstance roll back unselected resources
func (c *PickerObject) RollbackUnusedInstance() error {
	return model.UpdateTbRpDetailStatusAtSelling(c.SatisfiedHostIds, model.Unused)
}

// CampusNice build campus
type CampusNice struct {
	Campus string `json:"campus"`
	Count  int64  `json:"count"`
}

// CampusWrapper 园区排序
type CampusWrapper struct {
	Campus []CampusNice
	by     func(p, q *CampusNice) bool
}

// Len 用于排序
func (pw CampusWrapper) Len() int {
	return len(pw.Campus)
}

// Swap 用于排序
func (pw CampusWrapper) Swap(i, j int) {
	pw.Campus[i], pw.Campus[j] = pw.Campus[j], pw.Campus[i]
}

// Less 用于排序
func (pw CampusWrapper) Less(i, j int) bool {
	return pw.by(&pw.Campus[i], &pw.Campus[j])
}

// PickerDone picker done
func (c *PickerObject) PickerDone() bool {
	return len(c.SatisfiedHostIds) == c.Count
}

// InterSectForEquipment 求交集 EquipmentID
func (c *PickerObject) InterSectForEquipment(equipmentId string) int {
	baseSet := mapset.NewSet[string]()
	for _, v := range cmutil.RemoveDuplicate(c.ExistEquipmentIds) {
		baseSet.Add(v)
	}
	myset := mapset.NewSet[string]()
	myset.Add(equipmentId)
	return baseSet.Intersect(myset).Cardinality()
}

// InterSectForLinkNetDevice 求交集 LinkNetDeviceIds
func (c *PickerObject) InterSectForLinkNetDevice(linkDeviceIds []string) int {
	baseSet := mapset.NewSet[string]()
	for _, v := range cmutil.RemoveDuplicate(c.ExistLinkNetdeviceIds) {
		baseSet.Add(v)
	}
	myset := mapset.NewSet[string]()
	for _, linkId := range linkDeviceIds {
		if cmutil.IsNotEmpty(linkId) {
			myset.Add(linkId)
		}
	}
	return baseSet.Intersect(myset).Cardinality()
}

// InstanceObject instance object
type InstanceObject struct {
	BkHostId        int
	Equipment       string
	LinkNetdeviceId []string
	Nice            int64
	InsDetail       *model.TbRpDetail
}

// GetLinkNetDeviceIdsInterface getLinkNetDeviceIdsInterface
func (c *InstanceObject) GetLinkNetDeviceIdsInterface() []interface{} {
	var k []interface{}
	for _, v := range c.LinkNetdeviceId {
		k = append(k, v)
	}
	return k
}

// Wrapper Wrapper
type Wrapper struct {
	Instances []InstanceObject
	by        func(p, q *InstanceObject) bool
}

// SortBy sort by
type SortBy func(p, q *InstanceObject) bool

// Len 用于排序
func (pw Wrapper) Len() int { // 重写 Len() 方法
	return len(pw.Instances)
}

// Swap 用于排序
func (pw Wrapper) Swap(i, j int) { // 重写 Swap() 方法
	pw.Instances[i], pw.Instances[j] = pw.Instances[j], pw.Instances[i]
}

// Less 用于排序
func (pw Wrapper) Less(i, j int) bool { // 重写 Less() 方法
	return pw.by(&pw.Instances[i], &pw.Instances[j])
}
