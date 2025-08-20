/*
 * TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
 * Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
 * Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at https://opensource.org/licenses/MIT
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
 * an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations under the License.
 */

// Package manage resource manage
package manage

import (
	"encoding/json"
	"fmt"
	"time"

	"dbm-services/common/db-resource/internal/controller"
	"dbm-services/common/db-resource/internal/middleware"
	"dbm-services/common/db-resource/internal/model"
	"dbm-services/common/db-resource/internal/svr/bk"
	"dbm-services/common/go-pubpkg/cmutil"
	"dbm-services/common/go-pubpkg/logger"

	rf "github.com/gin-gonic/gin"
	"github.com/samber/lo"
)

// MachineResourceHandler 主机处理handler
type MachineResourceHandler struct {
	controller.BaseHandler
}

func init() {
	middleware.RequestLoggerFilter.Add("/resource/import")
	middleware.RequestLoggerFilter.Add("/resource/update")
	middleware.RequestLoggerFilter.Add("/resource/delete")
	middleware.RequestLoggerFilter.Add("/resource/batch/update")
	middleware.RequestLoggerFilter.Add("/resource/list")
}

// RegisterRouter 注册路由信息
func (c *MachineResourceHandler) RegisterRouter(engine *rf.Engine) {
	r := engine.Group("resource")
	{
		r.POST("/list", c.List)
		r.POST("/list/all", c.ListAll)
		r.POST("/list/osname", c.ListOsName)
		r.POST("/update", c.Update)
		r.POST("/batch/update", c.BatchUpdate)
		r.POST("/append/labels", c.AddLabels)
		r.POST("/delete", c.Delete)
		r.POST("/import", c.Import)
		r.POST("/reimport", c.ImportMachineWithDiffInfo)
		r.POST("/mountpoints", c.GetMountPoints)
		r.POST("/disktypes", c.GetDiskTypes)
		r.POST("/subzones", c.GetSubZones)
		r.POST("/deviceclass", c.GetDeviceClass)
		r.POST("/operation/list", c.OperationInfoList)
		r.POST("/operation/create", c.RecordImportResource)
		r.POST("/spec/sum", c.SpecSum)
		r.POST("/groupby/label/count", c.GroupByLabelCount)
		r.POST("/refresh/disk/info", c.RefreshDiskInfo)
	}
}

// MachineDeleteInputParam 删除主机参数
type MachineDeleteInputParam struct {
	BkHostIds []int `json:"bk_host_ids"  binding:"required"`
}

// Delete 删除主机
func (c *MachineResourceHandler) Delete(r *rf.Context) {
	var input MachineDeleteInputParam
	if err := c.Prepare(r, &input); err != nil {
		logger.Error("Prepare Error %s", err.Error())
		return
	}
	affect_row, err := model.DeleteTbRpDetail(input.BkHostIds)
	if err != nil {
		logger.Error("failed to delete data:%s", err.Error())
		c.SendResponse(r, err, nil)
		return
	}
	if affect_row == 0 {
		c.SendResponse(r, fmt.Errorf("no data was deleted"), nil)
		return
	}
	c.SendResponse(r, nil, "Delete Success")
}

// BatchUpdateMachineInput 批量编辑主机信息请求参数
type BatchUpdateMachineInput struct {
	BkHostIds []int  `json:"bk_host_ids"  binding:"required,dive,gt=0" `
	RackId    string `json:"rack_id"`
	UpdateRsMeta
}

// BatchUpdate 批量编辑主机信息
func (c *MachineResourceHandler) BatchUpdate(r *rf.Context) {
	var input BatchUpdateMachineInput
	var err error
	if err = c.Prepare(r, &input); err != nil {
		logger.Error("Prepare Error %s", err.Error())
		return
	}
	// update for biz
	updateMap, err := input.getUpdateMap()
	if err != nil {
		c.SendResponse(r, err, err.Error())
		return
	}
	// update rack id
	if cmutil.IsNotEmpty(input.RackId) {
		updateMap["rack_id"] = input.RackId
	}
	// do update
	err = model.DB.Self.Table(model.TbRpDetailName()).Where("bk_host_id in (?)", input.BkHostIds).Updates(updateMap).Error
	if err != nil {
		c.SendResponse(r, err, err.Error())
		return
	}
	// return response
	c.SendResponse(r, nil, "ok")
}

// MachineResourceInputParam 多个不同的主句的编辑的不同的参数
type MachineResourceInputParam struct {
	Data []MachineResource `json:"data" binding:"required,dive,gt=0"`
}

// MachineResource 主机参数
type MachineResource struct {
	BkHostID int `json:"bk_host_id" binding:"required"`
	UpdateRsMeta
}

// UpdateRsMeta TODO
type UpdateRsMeta struct {
	Labels        *[]string                `json:"labels,omitempty"`
	ForBiz        *int                     `json:"for_biz,omitempty"`
	RsType        *string                  `json:"resource_type,omitempty"`
	DeviceClass   *string                  `json:"device_class,omitempty"`
	RackId        *string                  `json:"rack_id,omitempty"`
	CityMeta      CityMeta                 `json:"city_meta,omitempty"`
	SubZoneMeta   SubZoneMeta              `json:"sub_zone_meta,omitempty"`
	StorageDevice map[string]bk.DiskDetail `json:"storage_device"`
}

// CityMeta 城市信息
type CityMeta struct {
	City   string `json:"city"`
	CityId string `json:"city_id"`
}

// SubZoneMeta sub zone 信息
type SubZoneMeta struct {
	SubZoneId string `json:"sub_zone_id"`
	SubZone   string `json:"sub_zone"`
}

func (v UpdateRsMeta) getUpdateMap() (updateMap map[string]interface{}, err error) {
	var labelJson, storageJson []byte
	updateMap = make(map[string]interface{})
	if v.Labels != nil {
		labelJson, err = json.Marshal(lo.Uniq(*v.Labels))
		if err != nil {
			logger.Error(fmt.Sprintf("Conversion LabelToJsonStr Failed,Error:%s", err.Error()))
			return updateMap, err
		}
		updateMap["labels"] = labelJson
	}
	updateMap["update_time"] = time.Now()
	if v.ForBiz != nil {
		updateMap["dedicated_biz"] = v.ForBiz
	}
	if v.RsType != nil {
		updateMap["rs_type"] = v.RsType
	}
	if v.DeviceClass != nil {
		updateMap["device_class"] = v.DeviceClass
	}
	if v.CityMeta.City != "" {
		updateMap["city"] = v.CityMeta.City
		updateMap["city_id"] = v.CityMeta.CityId
	}
	if v.SubZoneMeta.SubZoneId != "" {
		updateMap["sub_zone_id"] = v.SubZoneMeta.SubZoneId
		updateMap["sub_zone"] = v.SubZoneMeta.SubZone
	}
	if len(v.StorageDevice) > 0 {
		storageJson, err = json.Marshal(v.StorageDevice)
		if err != nil {
			logger.Error(fmt.Sprintf("Conversion storage device Failed,Error:%s", err.Error()))
			return updateMap, err
		}
		updateMap["storage_device"] = storageJson
	}
	return updateMap, err
}

// Update 编辑主机信息
func (c *MachineResourceHandler) Update(r *rf.Context) {
	var input MachineResourceInputParam
	if err := c.Prepare(r, &input); err != nil {
		logger.Error("Prepare Error %s", err.Error())
		return
	}
	logger.Debug(fmt.Sprintf("get params %v", input.Data))
	tx := model.DB.Self.Begin()
	for _, v := range input.Data {
		updateMap, err := v.getUpdateMap()
		if err != nil {
			logger.Error("Conversion resource types Failed,Error:%s", err.Error())
			c.SendResponse(r, err, err.Error())
			return
		}
		err = tx.Model(&model.TbRpDetail{}).Table(model.TbRpDetailName()).Where("bk_host_id=?", v.BkHostID).
			Updates(updateMap).Error
		if err != nil {
			tx.Rollback()
			logger.Error(fmt.Sprintf("Conversion resource types Failed,Error:%s", err.Error()))
			c.SendResponse(r, err, err.Error())
			return
		}
	}
	if err := tx.Commit().Error; err != nil {
		c.SendResponse(r, err, err.Error())
		return
	}
	c.SendResponse(r, nil, "Save Success")
}

// GetMountPoints get disk mount points
func (c MachineResourceHandler) GetMountPoints(r *rf.Context) {
	var rs []json.RawMessage

	if err := model.DB.Self.Table(model.TbRpDetailName()).Select("json_keys(storage_device)").
		Where("JSON_LENGTH(storage_device) > 0").Find(&rs).Error; err != nil {
		logger.Error("get mount points failed %s", err.Error())
		c.SendResponse(r, err, err.Error())
		return
	}

	var mountPoints []string
	for _, v := range rs {
		var mp []string
		if err := json.Unmarshal(v, &mp); err != nil {
			logger.Error("unmarshal failed %s", err.Error())
			c.SendResponse(r, err, err.Error())
			return
		}
		if len(mp) > 0 {
			mountPoints = append(mountPoints, mp...)
		}
	}
	c.SendResponse(r, nil, cmutil.RemoveDuplicate(mountPoints))
}

// GetDiskTypes get disk types
func (c MachineResourceHandler) GetDiskTypes(r *rf.Context) {
	var rs []json.RawMessage

	err := model.DB.Self.Table(model.TbRpDetailName()).Select("json_extract(storage_device,'$.*.\"disk_type\"')").
		Where("JSON_LENGTH(storage_device) > 0").
		Find(&rs).Error

	if err != nil {
		logger.Error("get DiskType failed %s", err.Error())
		c.SendResponse(r, err, err.Error())
		return
	}

	var diskTypes []string

	for _, v := range rs {
		var mp []string

		if err := json.Unmarshal(v, &mp); err != nil {
			logger.Error("unmarshal failed %s", err.Error())
			c.SendResponse(r, err, err.Error())
			return
		}

		if len(mp) > 0 {
			diskTypes = append(diskTypes, mp...)
		}
	}

	c.SendResponse(r, nil, cmutil.RemoveDuplicate(diskTypes))
}

// GetSubZoneParam get subzones param
type GetSubZoneParam struct {
	LogicCitys []string `json:"citys"`
}

// GetSubZones get subzones
func (c MachineResourceHandler) GetSubZones(r *rf.Context) {
	var input GetSubZoneParam
	if c.Prepare(r, &input) != nil {
		return
	}
	var subZones []string
	db := model.DB.Self.Table(model.TbRpDetailName())
	err := db.Distinct("sub_zone").Where("city in ? ", input.LogicCitys).Find(&subZones).Error
	if err != nil {
		c.SendResponse(r, err, err.Error())
		return
	}
	c.SendResponse(r, nil, subZones)
}

// GetDeviceClass 获取机型
func (c MachineResourceHandler) GetDeviceClass(r *rf.Context) {
	var class []string
	db := model.DB.Self.Table(model.TbRpDetailName())
	err := db.Distinct("device_class").Where("device_class !=''").Find(&class).Error
	if err != nil {
		c.SendResponse(r, err, err.Error())
		return
	}
	c.SendResponse(r, nil, class)
}

// GroupByLabelCount group by label count
func (c *MachineResourceHandler) GroupByLabelCount(r *rf.Context) {
	var rs []model.TbRpDetail
	err := model.DB.Self.Table(model.TbRpDetailName()).Find(&rs, "status = ?", model.Unused).Error
	if err != nil {
		c.SendResponse(r, err, err.Error())
		return
	}
	logger.Info("rs len %d", len(rs))
	ret := make(map[string]int)
	for _, v := range rs {
		var labels []string
		logger.Info("labels %s", string(v.Labels))
		if err := json.Unmarshal(v.Labels, &labels); err != nil {
			logger.Error("unmarshal failed %s", err.Error())
			c.SendResponse(r, err, err.Error())
			return
		}
		if len(labels) > 0 {
			for _, l := range lo.Uniq(labels) {
				ret[l]++
			}
		}
	}
	c.SendResponse(r, nil, ret)
}
