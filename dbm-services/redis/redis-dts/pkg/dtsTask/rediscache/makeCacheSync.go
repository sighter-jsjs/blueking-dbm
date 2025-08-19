package rediscache

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"dbm-services/redis/redis-dts/models/myredis"
	"dbm-services/redis/redis-dts/models/mysql/tendisdb"
	"dbm-services/redis/redis-dts/pkg/constvar"
	"dbm-services/redis/redis-dts/pkg/dtsTask"
	"dbm-services/redis/redis-dts/util"

	"github.com/jinzhu/gorm"
	"github.com/spf13/viper"
	"go.uber.org/zap"
)

const (
	// ShakeWaitFullStatus waitfull
	ShakeWaitFullStatus = "waitfull"
	// ShakeFullStatus full
	ShakeFullStatus = "full"
	// ShakeIncrStatus incr
	ShakeIncrStatus = "incr"

	//redis-shakeV4 status
	ShakeV4HandStatus       = "hand shaking"
	ShakeV4WaitFullStatus   = "waiting bgsave"
	ShakeV4ReceiveDdbStatus = "receiving rdb"
	ShakeV4FullStatus       = "syncing rdb"
	ShakeV4IncrStatus       = "syncing aof"
)

// MakeCacheSyncTask cache_task
type MakeCacheSyncTask struct {
	dtsTask.TendisDtsFatherTask
	RedisShakeBin string `json:"redisSahkeBin"`
	ShakeLogFile  string `json:"shakeLogFile"`
	ShakeConfFile string `json:"shakeConfFile"`
	SystemProfile int    `json:"systemProfile"`
	HTTPProfile   int    `json:"httpProfile"`
	SrcADDR       string `json:"srcAddr"`
	SrcPassword   string `json:"srcPassword"`
	SrcVersion    string `json:"srcVersion"`
	SrcBigVersion int    `json:"srcBigVersion"`
	DstADDR       string `json:"dstAddr"`
	DstPassword   string `json:"dstPassword"`
	DstVersion    string `json:"dstVersion"`
}

// TaskType task类型
func (task *MakeCacheSyncTask) TaskType() string {
	return constvar.MakeCacheSyncTaskType
}

// NextTask 下一个task类型
func (task *MakeCacheSyncTask) NextTask() string {
	return constvar.WatchCacheSyncTaskType
}

// NewMakeCacheSyncTask 新建一个 RedisShake启动task
func NewMakeCacheSyncTask(row *tendisdb.TbTendisDTSTask) *MakeCacheSyncTask {
	return &MakeCacheSyncTask{
		TendisDtsFatherTask: dtsTask.NewDtsFatherTask(row),
	}
}

// PreClear 关闭以前生成的redis-shake
func (task *MakeCacheSyncTask) PreClear() {
	if task.Err != nil {
		return
	}
	if task.RowData.SyncerPort == 0 {
		return
	}
	defer func() {
		// clear old sync config file and log file
		syncDir := task.MkSyncDirIfNotExists()
		if task.Err != nil {
			return
		}
		rmCmd := fmt.Sprintf("cd %s && rm -rf  *-taskid%d-*.conf *-taskid%d-*.toml *.log log/",
			syncDir, task.RowData.ID, task.RowData.ID)
		task.Logger.Info(fmt.Sprintf("makeCacheSync preClear execute:%s", rmCmd))
		util.RunLocalCmd("bash", []string{"-c", rmCmd}, "", nil, 10*time.Second, task.Logger)
	}()

	task.RedisShakeStop()
	return
}

// Execute 执行启动redis-shake
func (task *MakeCacheSyncTask) Execute() {
	if task.Err != nil {
		return
	}

	defer func() {
		if task.Err != nil {
			task.SetStatus(-1)
			task.SetMessage(task.Err.Error())
			task.UpdateRow()
		}
	}()

	task.SetStatus(1)
	task.UpdateDbAndLogLocal("开始启动redis-shake")

	srcPasswd, _ := base64.StdEncoding.DecodeString(task.RowData.SrcPassword)
	dstPasswd, _ := base64.StdEncoding.DecodeString(task.RowData.DstPassword)

	task.SrcADDR = fmt.Sprintf("%s:%d", task.RowData.SrcIP, task.RowData.SrcPort)
	task.SrcPassword = string(srcPasswd)
	task.DstADDR = task.RowData.DstCluster
	task.DstPassword = string(dstPasswd)

	task.HTTPProfile = task.RowData.SyncerPort
	task.SystemProfile = task.HTTPProfile + 1

	task.GetSrcRedisVersion()
	if task.Err != nil {
		return
	}

	isSyncOk := task.IsSyncStateOK()
	if isSyncOk {
		// 同步状态本来就是ok的,直接watcht redis-shake即可
		task.Logger.Info(fmt.Sprintf("redis:%s 同步状态ok,开始watch...", task.SrcADDR))
		task.SetTaskType(task.NextTask())
		task.SetStatus(0)
		task.UpdateRow()
		return
	}

	task.GetMyRedisShakeTool(true)
	if task.Err != nil {
		return
	}

	_, task.Err = util.IsFileExistsInCurrDir("redis-shake-template.conf")
	if task.Err != nil {
		task.Logger.Error(task.Err.Error())
		return
	}

	task.PreClear()
	if task.Err != nil {
		return
	}
	task.GetDestRedisVersion()
	if task.Err != nil {
		return
	}

	// 关闭目的集群slowlog
	task.DisableDstClusterSlowlog()

	task.RedisShakeStart(true)
	if task.Err != nil {
		return
	}
	task.WatchShake()
	if task.Err != nil {
		return
	}

	task.SetTaskType(task.NextTask())
	task.SetStatus(0)
	task.UpdateDbAndLogLocal("redis-shake 启动成功,pid:%d,开始修改taskType:%s taskStatus:%d",
		task.RowData.SyncerPid, task.RowData.TaskType, task.RowData.Status)

	return
}

// GetSrcRedisVersion 获取源redis的版本
func (task *MakeCacheSyncTask) GetSrcRedisVersion() {
	if task.SrcVersion != "" && task.SrcBigVersion != 0 {
		return
	}

	srcConn, err := myredis.NewRedisClient(task.SrcADDR, task.SrcPassword, 0, task.Logger)
	if err != nil {
		task.Err = err
		return
	}
	defer srcConn.Close()
	infoData, err := srcConn.Info("server")
	if err != nil {
		task.Err = fmt.Errorf("srcRedis:%s both not support 'info server'", task.SrcADDR)
		task.Logger.Error(task.Err.Error())
		return
	}
	task.SrcVersion = infoData["redis_version"]
	redisBigVerison, err := strconv.Atoi(strings.Split(task.SrcVersion, ".")[0])
	if err != nil {
		task.Logger.Warn(fmt.Sprintf("get src redis big version error, %+v", err.Error()))
		return
	}
	task.SrcBigVersion = redisBigVerison
	task.Logger.Info("get srcVersion:" + task.SrcVersion)
}

// GetDestRedisVersion
// 通过info server命令获取目的redis版本;
// 如果目的redis不支持info server命令,则用源redis版本当做目的redis版本;
// 如果源redis、目的redis均不支持info server命令,则报错;
func (task *MakeCacheSyncTask) GetDestRedisVersion() {
	if task.DstVersion != "" {
		return
	}
	srcConn, err := myredis.NewRedisClient(task.SrcADDR, task.SrcPassword, 0, task.Logger)
	if err != nil {
		task.Err = err
		return
	}
	defer srcConn.Close()
	destConn, err := myredis.NewRedisClient(task.DstADDR, task.DstPassword, 0, task.Logger)
	if err != nil {
		task.Err = err
		return
	}
	defer destConn.Close()

	infoData, err := destConn.Info("server")
	_, ok := infoData["redis_version"]
	if err == nil && ok {
		task.DstVersion = infoData["redis_version"]
		return
	}
	infoData, err = srcConn.Info("server")
	if err != nil {
		task.Err = fmt.Errorf("srcRedis:%s dstRedis:%s both not support 'info server'",
			task.SrcADDR, task.DstADDR)
		task.Logger.Error(task.Err.Error())
		return
	}
	task.DstVersion = infoData["redis_version"]
	task.Logger.Info("get targetVersion:" + task.DstVersion)

}

// MkSyncDirIfNotExists create sync directory if not exists
func (task *MakeCacheSyncTask) MkSyncDirIfNotExists() (syncDir string) {
	err := task.InitTaskDir()
	if err != nil {
		task.Err = err
		return
	}
	return task.TaskDir
}

// IsRedisShakeAlive redis-shake是否存活
func (task *MakeCacheSyncTask) IsRedisShakeAlive() (isAlive bool, err error) {
	isSyncAliaveCmd := fmt.Sprintf("ps -ef|grep %s_%d|grep 'taskid%d-'|grep -v grep|grep 'redis-shake'|grep -E 'toml|conf' || true",
		task.RowData.SrcIP, task.RowData.SrcPort, task.RowData.ID)
	task.Logger.Info("", zap.String("isSyncAliaveCmd", isSyncAliaveCmd))
	ret, err := util.RunLocalCmd("bash", []string{"-c", isSyncAliaveCmd}, "", nil, 1*time.Minute, task.Logger)
	if err != nil {
		task.Logger.Error("RedisSyncStop IsSyncAlive fail", zap.Error(err))
		return false, err
	}
	ret = strings.TrimSpace(ret)
	if ret != "" {
		return true, nil
	}
	return false, nil
}

// IsSyncStateOK 同步状态是否本来就ok
func (task *MakeCacheSyncTask) IsSyncStateOK() (ok bool) {
	// redis-shake进程是否活着
	ok, task.Err = task.IsRedisShakeAlive()
	if task.Err != nil {
		return false
	}
	if !ok {
		return false
	}
	getHttpProfileCmd := fmt.Sprintf(`
	confFile=$(ps -ef|grep %s_%d|grep 'taskid%d-'|grep -v grep|grep 'redis-shake'| \
	grep -E 'toml|conf'|grep -P --only-match "\-conf (.*.conf)$|redis-shake-v4 (.*.toml)$"|awk '{print $2}')
	if [ -n "$confFile" ] &&  [ -f "$confFile" ]
	then
			ret=$(grep -iP "^http_profile|^status_port" $confFile|awk '{print $3}')
			echo $ret
	else
			echo "0000"
	fi
	`, task.RowData.SrcIP, task.RowData.SrcPort, task.RowData.ID)
	task.Logger.Info("IsSyncStateOK ", zap.String("getHttpProfileCmd", getHttpProfileCmd))
	ret, err := util.RunLocalCmd("bash", []string{"-c", getHttpProfileCmd}, "", nil, 1*time.Minute, task.Logger)
	if err != nil {
		task.Logger.Error("IsSyncStateOK fail", zap.Error(err))
		return false
	}
	ret = strings.TrimSpace(ret)
	task.Logger.Info("IsSyncStateOK ", zap.String("getHttpProfileCmd result:", ret))
	if ret == "0000" || ret == "" {
		return false
	}
	task.HTTPProfile, _ = strconv.Atoi(ret)
	task.SystemProfile = task.HTTPProfile + 1
	task.SetSyncerPort(task.HTTPProfile)
	task.UpdateRow()
	// redis-shake 获取metrics是否成功
	metrics := task.GetShakeMerics()
	if task.Err != nil {
		return false
	}
	if metrics == nil {
		return false
	}
	return true
}

// RedisShakeStop 关闭redis-shake
func (task *MakeCacheSyncTask) RedisShakeStop() {
	var err error
	var isAlive bool
	isAlive, err = task.IsRedisShakeAlive()
	if isAlive == false {
		task.Logger.Info(fmt.Sprintf("RedisShakeStop srcRedis:%s#%d sync is not alive", task.RowData.SrcIP,
			task.RowData.SrcPort))
		return
	}
	task.Logger.Info(fmt.Sprintf("RedisShakeStop srcRedis:%s#%d sync is alive", task.RowData.SrcIP, task.RowData.SrcPort))

	// kill redis-shake
	killCmd := fmt.Sprintf(`
	ps -ef|grep %s_%d|grep 'taskid%d-'|grep -v grep|grep 'redis-shake'|grep -E 'toml|conf' |awk '{print $2}'|while read pid
	do
	kill -9 $pid
	done
	`, task.RowData.SrcIP, task.RowData.SrcPort, task.RowData.ID)
	task.Logger.Info("RedisShakeStop...", zap.String("killCmd", killCmd))
	retryTimes := 0
	for isAlive == true && retryTimes < 5 {
		msg := fmt.Sprintf("Killing redis-shake  times:%d ...", retryTimes+1)
		task.Logger.Info(msg)
		// redis-shake is alive, now kill it
		_, err = util.RunLocalCmd("bash", []string{"-c", killCmd}, "", nil, 1*time.Minute, task.Logger)
		if err != nil {
			task.Logger.Error("Kill redis-shake process fail", zap.Error(err))
		}
		time.Sleep(10 * time.Second)
		retryTimes++
		isAlive, _ = task.IsRedisShakeAlive()
		if isAlive == true {
			task.Logger.Error(fmt.Sprintf("srcRedis:%s#%d,Kill redis-shake fail,process still alive",
				task.RowData.SrcIP, task.RowData.SrcPort))
		}
	}
	if isAlive == true && retryTimes == 5 {
		task.Logger.Error(fmt.Sprintf("srcRedis:%s#%d,Kill redis-shake process failed", task.RowData.SrcIP,
			task.RowData.SrcPort))
		task.Err = fmt.Errorf("Kill redis-shake process failed")
		return
	}
	task.Logger.Info(fmt.Sprintf("srcRedis:%s#%d,kill redis-shake success", task.RowData.SrcIP, task.RowData.SrcPort))
	return
}

// GetMyRedisShakeTool Get [latest] redis-shake tool
func (task *MakeCacheSyncTask) GetMyRedisShakeTool(fetchLatest bool) {
	task.GetRedisShakeToolFromLocal()
	return
}

// GetRedisShakeToolFromLocal 本地获取redis-shake
func (task *MakeCacheSyncTask) GetRedisShakeToolFromLocal() {
	currentPath, err := util.CurrentExecutePath()
	if err != nil {
		task.Err = err
		task.Logger.Error(err.Error())
		return
	}
	shakeBin := filepath.Join(currentPath, "redis-shake")
	_, err = os.Stat(shakeBin)
	if err != nil && os.IsNotExist(err) == true {
		task.Err = fmt.Errorf("%s not exists,err:%v", shakeBin, err)
		task.Logger.Error(task.Err.Error())
		return
	} else if err != nil && os.IsPermission(err) == true {
		err = os.Chmod(shakeBin, 0774)
		if err != nil {
			task.Err = fmt.Errorf("%s os.Chmod 0774 fail,err:%v", shakeBin, err)
			task.Logger.Error(task.Err.Error())
			return
		}
	}
	task.Logger.Info(fmt.Sprintf("%s is ok", shakeBin))
	task.RedisShakeBin = shakeBin
}

// getMySyncPort 获取redis-shake port, 20000<=port<30000
func (task *MakeCacheSyncTask) getMySyncPort(initSyncPort int) {
	taskTypes := []string{}
	var syncerport int
	taskTypes = append(taskTypes, constvar.MakeCacheSyncTaskType)
	taskTypes = append(taskTypes, constvar.WatchCacheSyncTaskType)
	if initSyncPort <= 0 {
		initSyncPort = 20000
		localIP, _ := util.GetLocalIP()
		dtsSvrMaxSyncPortTask, err := tendisdb.GetDtsSvrMaxSyncPort(task.RowData.BkCloudID, localIP,
			constvar.TendisTypeRedisInstance, taskTypes, task.Logger)
		if (err != nil && gorm.IsRecordNotFoundError(err)) || dtsSvrMaxSyncPortTask == nil {
			initSyncPort = 20000
		} else if err != nil {
			task.Err = err
			return
		} else {
			if dtsSvrMaxSyncPortTask.SyncerPort >= 20000 {
				initSyncPort = dtsSvrMaxSyncPortTask.SyncerPort + 2 // 必须加2
			}
		}
	}
	if initSyncPort > 30000 {
		initSyncPort = 20000
	}
	syncerport, task.Err = util.GetANotUsePort("127.0.0.1", initSyncPort, 2)
	if task.Err != nil {
		task.Logger.Error(task.Err.Error())
		return
	}
	task.SetSyncerPort(syncerport)
	task.UpdateRow()
	task.HTTPProfile = task.RowData.SyncerPort
	task.SystemProfile = task.HTTPProfile + 1

	return
}
func (task *MakeCacheSyncTask) clearOldShakeConfigFile() {
	task.ShakeConfFile = strings.TrimSpace(task.ShakeConfFile)
	if task.ShakeConfFile == "" {
		return
	}
	_, err := os.Stat(task.ShakeConfFile)
	if err == nil {
		// rm old sync log file
		rmCmd := fmt.Sprintf("cd %s && rm -rf %s",
			filepath.Dir(task.ShakeConfFile), filepath.Base(task.ShakeLogFile))
		task.Logger.Info(rmCmd)
		util.RunLocalCmd("bash", []string{"-c", rmCmd}, "", nil, 20*time.Second, task.Logger)
	}
}
func (task *MakeCacheSyncTask) clearOldShakeLogFile() {
	task.ShakeLogFile = strings.TrimSpace(task.ShakeLogFile)
	if task.ShakeLogFile == "" {
		return
	}
	_, err := os.Stat(task.ShakeLogFile)
	if err == nil {
		// rm old sync log file
		rmCmd := fmt.Sprintf("cd %s && rm -rf *.log",
			filepath.Dir(task.ShakeLogFile))
		task.Logger.Info(rmCmd)
		util.RunLocalCmd("bash", []string{"-c", rmCmd}, "", nil, 20*time.Second, task.Logger)
	}
}

// createShakeV4ConfigFile 生成redis-shakeV4版本的配置文件。后缀为toml
func (task *MakeCacheSyncTask) createShakeV4ConfigFile() {
	syncDir := task.MkSyncDirIfNotExists()
	if task.Err != nil {
		return
	}
	task.ShakeConfFile = filepath.Join(syncDir,
		fmt.Sprintf("shake-taskid%d-%d.toml", task.RowData.ID, task.RowData.SyncerPort))

	_, err := os.Stat(task.ShakeConfFile)
	if err == nil {
		// if config file exists,return
		task.Logger.Info(fmt.Sprintf("redis-shake config file:%s already exists", task.ShakeConfFile))
		return
	}

	currentPath, _ := util.CurrentExecutePath()
	tempFile := filepath.Join(currentPath, "redis-shake-template.toml")
	tempContent, err := ioutil.ReadFile(tempFile)
	if err != nil {
		task.Logger.Error("Read redis-shake template conf fail",
			zap.Error(err), zap.String("templateConfig", tempFile))
		task.Err = fmt.Errorf("Read redis-shake template conf fail.err:%v", err)
		return
	}
	loglevel := "info"
	debug := viper.GetBool("TENDIS_DEBUG")
	if debug == true {
		loglevel = "debug"
	}
	keyWhiteRegex, keyBlackRegex := "*", ""
	if task.RowData.KeyWhiteRegex != "" && !task.IsMatchAny(task.RowData.KeyWhiteRegex) {
		keyWhiteRegex = task.RowData.KeyWhiteRegex
	}
	if task.RowData.KeyBlackRegex != "" && !task.IsMatchAny(task.RowData.KeyBlackRegex) {
		keyBlackRegex = task.RowData.KeyBlackRegex // V4配置文件变动
	}

	// WriteMode=delete_and_write_to_redis/flushall_and_write_to_redis
	// 都需要用 restore [replace]
	// redis-shakeV4 只支持 panic, rewrite or skip，
	keyExists := "rewrite"
	if task.RowData.WriteMode == constvar.WriteModeKeepAndAppendToRedis {
		// 设置这两个参数后,redis-shake将通过 hset/rpush等命令同步数据
		// 而不是restore 命令同步数据
		keyExists = "skip"
	}

	// V4更新下log file，只需要文件名。最终文件是：PID_PATH/LOG_FILE
	task.ShakeLogFile = filepath.Join(filepath.Dir(task.ShakeConfFile), filepath.Base(task.ShakeLogFile))
	tempData := string(tempContent)
	tempData = strings.ReplaceAll(tempData, "{{LOG_FILE}}", filepath.Base(task.ShakeLogFile))
	tempData = strings.ReplaceAll(tempData, "{{LOG_LEVEL}}", loglevel)
	tempData = strings.ReplaceAll(tempData, "{{PID_PATH}}", filepath.Dir(task.ShakeConfFile))
	tempData = strings.ReplaceAll(tempData, "{{SYSTEM_PROFILE}}", strconv.Itoa(task.SystemProfile))
	tempData = strings.ReplaceAll(tempData, "{{HTTP_PROFILE}}", strconv.Itoa(task.HTTPProfile))
	tempData = strings.ReplaceAll(tempData, "{{SRC_ADDR}}", task.SrcADDR)
	tempData = strings.ReplaceAll(tempData, "{{SRC_PASSWORD}}", task.SrcPassword)
	tempData = strings.ReplaceAll(tempData, "{{TARGET_ADDR}}", task.DstADDR)
	tempData = strings.ReplaceAll(tempData, "{{TARGET_PASSWORD}}", task.DstPassword)
	tempData = strings.ReplaceAll(tempData, "{{KEY_WHITE_REGEX}}", keyWhiteRegex)
	tempData = strings.ReplaceAll(tempData, "{{KEY_BLACK_REGEX}}", keyBlackRegex)
	tempData = strings.ReplaceAll(tempData, "{{KEY_EXISTS}}", keyExists)
	err = ioutil.WriteFile(task.ShakeConfFile, []byte(tempData), 0755)

	if err != nil {
		task.Logger.Error("Save redis-shake toml fail", zap.Error(err), zap.String("syncConfig", task.ShakeConfFile))
		task.Err = fmt.Errorf("Save redis-shake toml fail.err:%v", err)
		return
	}
	task.Logger.Info(fmt.Sprintf("create redis-shake toml file:%s success", task.ShakeConfFile))

	// 更新一下task.RedisShakeBin = shakeBin
	shakeBin := filepath.Join(currentPath, "redis-shake-v4")
	_, err = os.Stat(shakeBin)
	if err != nil && os.IsNotExist(err) == true {
		task.Err = fmt.Errorf("%s not exists,err:%v", shakeBin, err)
		task.Logger.Error(task.Err.Error())
		return
	} else if err != nil && os.IsPermission(err) == true {
		err = os.Chmod(shakeBin, 0774)
		if err != nil {
			task.Err = fmt.Errorf("%s os.Chmod 0774 fail,err:%v", shakeBin, err)
			task.Logger.Error(task.Err.Error())
			return
		}
	}
	task.Logger.Info(fmt.Sprintf("%s is ok. redis version is %s. will update shakebin",
		shakeBin, task.SrcVersion))
	task.RedisShakeBin = shakeBin
	return
}

// createShakeConfigFile create redis-shake config file if not exists
func (task *MakeCacheSyncTask) createShakeConfigFile() {
	syncDir := task.MkSyncDirIfNotExists()
	if task.Err != nil {
		return
	}
	task.ShakeConfFile = filepath.Join(syncDir,
		fmt.Sprintf("shake-taskid%d-%d.conf", task.RowData.ID, task.RowData.SyncerPort))

	_, err := os.Stat(task.ShakeConfFile)
	if err == nil {
		// if config file exists,return
		task.Logger.Info(fmt.Sprintf("redis-shake config file:%s already exists", task.ShakeConfFile))
		return
	}

	currentPath, _ := util.CurrentExecutePath()
	tempFile := filepath.Join(currentPath, "redis-shake-template.conf")
	tempContent, err := ioutil.ReadFile(tempFile)
	if err != nil {
		task.Logger.Error("Read redis-shake template conf fail",
			zap.Error(err), zap.String("templateConfig", tempFile))
		task.Err = fmt.Errorf("Read redis-shake template conf fail.err:%v", err)
		return
	}
	loglevel := "info"
	debug := viper.GetBool("TENDIS_DEBUG")
	if debug == true {
		loglevel = "debug"
	}
	startSeg := -1
	endSeg := -1
	if task.RowData.SrcSegStart >= 0 &&
		task.RowData.SrcSegEnd <= 419999 &&
		task.RowData.SrcSegStart < task.RowData.SrcSegEnd {
		if task.RowData.SrcSegStart < 0 || task.RowData.SrcSegEnd < 0 {
			task.Err = fmt.Errorf("srcTendis:%s#%d segStart:%d<0 or segEnd:%d<0",
				task.RowData.SrcIP, task.RowData.SrcPort, task.RowData.SrcSegStart, task.RowData.SrcSegEnd)
			task.Logger.Error(task.Err.Error())
			return
		}
		if task.RowData.SrcSegStart >= task.RowData.SrcSegEnd {
			task.Err = fmt.Errorf("srcTendis:%s#%d segStart:%d >= segEnd:%d",
				task.RowData.SrcIP, task.RowData.SrcPort, task.RowData.SrcSegStart, task.RowData.SrcSegEnd)
			task.Logger.Error(task.Err.Error())
			return
		}
		startSeg = task.RowData.SrcSegStart
		endSeg = task.RowData.SrcSegEnd
	}
	keyWhiteRegex, keyBlackRegex := "", ""
	if task.RowData.KeyWhiteRegex != "" && !task.IsMatchAny(task.RowData.KeyWhiteRegex) {
		keyWhiteRegex = task.RowData.KeyWhiteRegex
	}
	if task.RowData.KeyBlackRegex != "" && !task.IsMatchAny(task.RowData.KeyBlackRegex) {
		keyBlackRegex = ";" + task.RowData.KeyBlackRegex // 注意最前面有个分号
	}
	var twemproxyHashTagEnabled = "false"
	if task.RowData.SrcTwemproxyHashTagEnabled == 1 {
		twemproxyHashTagEnabled = "true"
	}
	// WriteMode=delete_and_write_to_redis/flushall_and_write_to_redis
	// 都需要用 restore [replace]
	keyExists := "rewrite"
	// 如果目标集群是ssd或者plus，需要将bigKeyThreshold设置成1。
	// 可能还得考虑低版本proxy问题，直接简化处理，所有架构都不用restore
	bigKeyThreshold := 1
	if task.RowData.WriteMode == constvar.WriteModeKeepAndAppendToRedis {
		// 设置这两个参数后,redis-shake将通过 hset/rpush等命令同步数据
		// 而不是restore 命令同步数据
		keyExists = "ignore"
		bigKeyThreshold = 1
	}

	tempData := string(tempContent)
	tempData = strings.ReplaceAll(tempData, "{{LOG_FILE}}", task.ShakeLogFile)
	tempData = strings.ReplaceAll(tempData, "{{LOG_LEVEL}}", loglevel)
	tempData = strings.ReplaceAll(tempData, "{{PID_PATH}}", filepath.Dir(task.ShakeConfFile))
	tempData = strings.ReplaceAll(tempData, "{{SYSTEM_PROFILE}}", strconv.Itoa(task.SystemProfile))
	tempData = strings.ReplaceAll(tempData, "{{HTTP_PROFILE}}", strconv.Itoa(task.HTTPProfile))
	tempData = strings.ReplaceAll(tempData, "{{SRC_ADDR}}", task.SrcADDR)
	tempData = strings.ReplaceAll(tempData, "{{SRC_PASSWORD}}", task.SrcPassword)
	tempData = strings.ReplaceAll(tempData, "{{START_SEGMENT}}", strconv.Itoa(startSeg))
	tempData = strings.ReplaceAll(tempData, "{{END_SEGMENT}}", strconv.Itoa(endSeg))
	tempData = strings.ReplaceAll(tempData, "{{TWEMPROXY_HASH_TAG_ENABLED}}", twemproxyHashTagEnabled)
	tempData = strings.ReplaceAll(tempData, "{{TARGET_ADDR}}", task.DstADDR)
	tempData = strings.ReplaceAll(tempData, "{{TARGET_PASSWORD}}", task.DstPassword)
	tempData = strings.ReplaceAll(tempData, "{{TARGET_VERSION}}", task.DstVersion)
	tempData = strings.ReplaceAll(tempData, "{{KEY_WHITE_REGEX}}", keyWhiteRegex)
	tempData = strings.ReplaceAll(tempData, "{{KEY_BLACK_REGEX}}", keyBlackRegex)
	tempData = strings.ReplaceAll(tempData, "{{KEY_EXISTS}}", keyExists)
	tempData = strings.ReplaceAll(tempData, "{{BIG_KEY_THRESHOLD}}", strconv.Itoa(bigKeyThreshold))

	err = ioutil.WriteFile(task.ShakeConfFile, []byte(tempData), 0755)
	if err != nil {
		task.Logger.Error("Save redis-shake conf fail", zap.Error(err), zap.String("syncConfig", task.ShakeConfFile))
		task.Err = fmt.Errorf("Save redis-shake conf fail.err:%v", err)
		return
	}
	task.Logger.Info(fmt.Sprintf("create redis-shake config file:%s success", task.ShakeConfFile))
	return
}
func (task *MakeCacheSyncTask) createShakeLogFile() {
	syncDir := task.MkSyncDirIfNotExists()
	if task.Err != nil {
		return
	}
	logDir := filepath.Join(syncDir, "log")
	util.MkDirIfNotExists(logDir)
	task.ShakeLogFile = filepath.Join(logDir,
		fmt.Sprintf("%s-%d-%d.log", task.RowData.SrcIP, task.RowData.SrcPort, task.RowData.SyncerPort))
	return
}

// RedisShakeStart 启动redis-shake
func (task *MakeCacheSyncTask) RedisShakeStart(reacquirePort bool) {
	task.Logger.Info(fmt.Sprintf("redis-shake start 源%s 目的%s ...", task.SrcADDR, task.DstADDR))
	defer task.Logger.Info("end redis-shake start")

	dtsTask.PortSyncerMut.Lock() // 串行获取redis-shake端口 和 启动
	defer dtsTask.PortSyncerMut.Unlock()

	if reacquirePort == true {
		task.getMySyncPort(0)
		if task.Err != nil {
			return
		}
	}
	maxRetryTimes := 5
	for maxRetryTimes >= 0 {
		maxRetryTimes--
		task.Err = nil
		task.createShakeLogFile()
		if task.Err != nil {
			return
		}

		logFile, err := os.OpenFile(task.ShakeLogFile, os.O_RDWR|os.O_CREATE, 0755)
		if err != nil {
			task.Logger.Error("open logfile fail", zap.Error(err), zap.String("syncLogFile", task.ShakeLogFile))
			task.Err = fmt.Errorf("open logfile fail,err:%v syncLogFile:%s", err, task.ShakeLogFile)
			return
		}

		var cmd *exec.Cmd
		var logCmd string
		ctx, cancel := context.WithCancel(context.Background())
		// redis7版本以上用redis-shake V4 去做同步
		if err == nil && task.SrcBigVersion >= getRedisShakeV4BeginVersion() {
			task.createShakeV4ConfigFile()
			logCmd = fmt.Sprintf("%s %s", task.RedisShakeBin, task.ShakeConfFile)
			task.Logger.Info(logCmd)
			cmd = exec.CommandContext(ctx, task.RedisShakeBin, task.ShakeConfFile)

		} else {
			task.createShakeConfigFile()
			logCmd = fmt.Sprintf("%s -type=sync -conf=%s", task.RedisShakeBin, task.ShakeConfFile)
			task.Logger.Info(logCmd)
			cmd = exec.CommandContext(ctx, task.RedisShakeBin, "-type", "sync", "-conf", task.ShakeConfFile)

		}
		if task.Err != nil {
			return
		}
		cmd.Stdout = logFile
		cmd.Stderr = logFile
		err = cmd.Start()
		if err != nil {
			defer cancel()
			logFile.Close()
			task.Logger.Error("cmd.Start fail", zap.Error(err), zap.String("cmd", logCmd))
			task.Err = fmt.Errorf("cmd.Start fail,err:%v command:%s", err, logCmd)
			return
		}
		go func() {
			err = cmd.Wait()
			if err != nil {
				task.Logger.Error("redis-shake cmd.wait error", zap.Error(err))
			}
		}()
		time.Sleep(5 * time.Second)
		isAlive, err := task.IsRedisShakeAlive()
		if err != nil {
			defer cancel()
			logFile.Close()
			task.Err = err
			task.Logger.Error(task.Err.Error())
			return
		}
		if isAlive == false {
			defer cancel()
			logFile.Close()
			logContent, _ := ioutil.ReadFile(task.ShakeLogFile)
			task.Logger.Error("redis-shake start fail", zap.String("failDetail", string(logContent)))
			task.Err = fmt.Errorf("redis-shake start fail,detail:%s", string(logContent))
			if strings.Contains(string(logContent), "address already in use") {
				// port address already used
				// clear and get sync port again and  retry
				task.clearOldShakeLogFile()
				task.clearOldShakeConfigFile()
				task.getMySyncPort(task.RowData.SyncerPort + 2)
				if task.Err != nil {
					return
				}
				continue
			}
		}
		task.SetSyncerPid(cmd.Process.Pid)
		break
	}
	if task.Err != nil {
		task.Err = fmt.Errorf("redis-shake start fail")
		return
	}
	task.UpdateDbAndLogLocal("redis-shake %d start success", task.RowData.SyncerPort)

	return
}

// WatchShake 监听redis-shake,binlog-lag与last-key等信息
func (task *MakeCacheSyncTask) WatchShake() {

	for {
		time.Sleep(10 * time.Second)
		row01, err := tendisdb.GetTaskByID(task.RowData.ID, task.Logger)
		if err != nil {
			task.Err = err
			return
		}
		if row01 == nil {
			task.UpdateDbAndLogLocal("根据task_id:%d获取task row失败,row01:%v", task.RowData.ID, row01)
			continue
		}
		task.RowData = row01
		if task.RowData.KillSyncer == 1 ||
			task.RowData.SyncOperate == constvar.RedisSyncStopTodo ||
			task.RowData.SyncOperate == constvar.RedisForceKillTaskTodo { // stop redis-shake

			succ := constvar.RedisSyncStopSucc
			fail := constvar.RedisSyncStopFail
			if task.RowData.SyncOperate == constvar.RedisForceKillTaskTodo {
				succ = constvar.RedisForceKillTaskSuccess
				fail = constvar.RedisForceKillTaskFail
			}
			task.Logger.Info(fmt.Sprintf("start execute %q ...", task.RowData.SyncOperate))
			task.RedisShakeStop()
			task.EnableDstClusterSlowlog() // 开启目的集群慢查询日志
			if task.Err == nil {
				task.SetSyncOperate(succ)
				task.SetStatus(2)
				task.UpdateDbAndLogLocal("redis-shake:%d终止成功", task.RowData.SyncerPid)
				task.Err = nil
			} else {
				task.SetSyncOperate(fail)
			}
			task.Logger.Info(fmt.Sprintf("end %q ...", task.RowData.SyncOperate))
			return
		}
		metric := task.GetShakeMerics()
		if task.Err != nil {
			return
		}
		if metric == nil {
			task.SetStatus(1)
			task.UpdateDbAndLogLocal("获取metic失败,retry...")
			continue
		}
		if metric.Status == ShakeWaitFullStatus {
			task.SetStatus(1)
			task.UpdateDbAndLogLocal("等待源实例执行bgsave...")
			continue
		}
		if metric.Status == ShakeFullStatus {
			task.SetStatus(1)
			task.UpdateDbAndLogLocal("rdb导入中,进度:%d%%", metric.FullSyncProgress)
			continue
		}
		if metric.Status == ShakeIncrStatus {
			task.SetMessage("增量同步中,延迟:%s", metric.Delay)
			task.SetStatus(1)
			task.UpdateRow()
			if task.RowData.TaskType == constvar.MakeCacheSyncTaskType {
				// makeCacheSync 在确保rdb导入完成后,增量数据同步状态由 watchCacheSync 来完成
				return
			}
		}

		// add redis-shake v4 status
		if metric.Status == ShakeV4HandStatus {
			task.SetStatus(1)
			task.UpdateDbAndLogLocal("redis-shake is handing.....")
			continue
		}
		if metric.Status == ShakeV4WaitFullStatus {
			task.SetStatus(1)
			task.UpdateDbAndLogLocal("等待源实例执行bgsave...")
			continue
		}
		if metric.Status == ShakeV4ReceiveDdbStatus {
			task.SetStatus(1)
			task.UpdateDbAndLogLocal("接收源实例RDB, 进度:%s-%d%%", metric.FullSyncProgressHuman, metric.FullSyncProgress)
			continue
		}
		if metric.Status == ShakeV4FullStatus {
			task.SetStatus(1)
			task.UpdateDbAndLogLocal("rdb导入中,进度:%s-%d%%", metric.FullSyncProgressHuman, metric.FullSyncProgress)
			continue
		}
		if metric.Status == ShakeV4IncrStatus {
			task.SetMessage("增量同步中,延迟:%s", metric.Delay)
			task.SetStatus(1)
			task.UpdateRow()
			if task.RowData.TaskType == constvar.MakeCacheSyncTaskType {
				// makeCacheSync 在确保rdb导入完成后,增量数据同步状态由 watchCacheSync 来完成
				return
			}
		}
		continue
	}
}

// UpgradeShakeMedia 更新redis-shake介质
func (task *MakeCacheSyncTask) UpgradeShakeMedia() {
	defer func() {
		if task.Err != nil {
			task.SetSyncOperate(constvar.RedisSyncUpgradeFail)
		}
	}()
	// stop redis-shake
	task.RedisShakeStop()
	if task.Err != nil {
		return
	}
	task.GetMyRedisShakeTool(true)
	if task.Err != nil {
		return
	}
	task.RedisShakeStart(false)
	if task.Err != nil {
		return
	}
}

// RedisShakeMetric shake meric
type RedisShakeMetric struct {
	StartTime             time.Time   `json:"StartTime"`
	PullCmdCount          int         `json:"PullCmdCount"`
	PullCmdCountTotal     int         `json:"PullCmdCountTotal"`
	BypassCmdCount        int         `json:"BypassCmdCount"`
	BypassCmdCountTotal   int         `json:"BypassCmdCountTotal"`
	PushCmdCount          int         `json:"PushCmdCount"`
	PushCmdCountTotal     int         `json:"PushCmdCountTotal"`
	SuccessCmdCount       int         `json:"SuccessCmdCount"`
	SuccessCmdCountTotal  int         `json:"SuccessCmdCountTotal"`
	FailCmdCount          int         `json:"FailCmdCount"`
	FailCmdCountTotal     int         `json:"FailCmdCountTotal"`
	Delay                 string      `json:"Delay"`
	AvgDelay              string      `json:"AvgDelay"`
	NetworkSpeed          int         `json:"NetworkSpeed"`
	NetworkFlowTotal      int         `json:"NetworkFlowTotal"`
	FullSyncProgress      int         `json:"FullSyncProgress"`
	FullSyncProgressHuman string      `json:"FullSyncProgressHuman"`
	Status                string      `json:"Status"`
	SenderBufCount        int         `json:"SenderBufCount"`
	ProcessingCmdCount    int         `json:"ProcessingCmdCount"`
	TargetDBOffset        int         `json:"TargetDBOffset"`
	SourceDBOffset        int         `json:"SourceDBOffset"`
	SourceAddress         string      `json:"SourceAddress"`
	TargetAddress         []string    `json:"TargetAddress"`
	Details               interface{} `json:"Details"`
}

type ReaderStatus struct {
	Name              string `json:"name"`
	Address           string `json:"address"`
	Dir               string `json:"dir"`
	Status            string `json:"status"`
	RdbFileSizeBytes  int    `json:"rdb_file_size_bytes"`
	RdbFileSizeHuman  string `json:"rdb_file_size_human"`
	RdbReceivedBytes  int    `json:"rdb_received_bytes"`
	RdbReceivedHuman  string `json:"rdb_received_human"`
	RdbSentBytes      int    `json:"rdb_sent_bytes"`
	RdbSentHuman      string `json:"rdb_sent_human"`
	AofReceivedOffset int    `json:"aof_received_offset"`
	AofSentOffset     int    `json:"aof_sent_offset"`
	AofReceivedBytes  int    `json:"aof_received_bytes"`
	AofReceivedHuman  string `json:"aof_received_human"`
}

// RedisShakeV4Metric shake v4 meric
type RedisShakeV4Metric struct {
	Consistent bool         `json:"consistent"`
	Reader     ReaderStatus `json:"reader"`
}

// GetShakeMerics get shake metric
func (task *MakeCacheSyncTask) GetShakeMerics() *RedisShakeMetric {
	var url string
	var resp []byte
	maxRetryTimes := 6
	for maxRetryTimes >= 0 {
		maxRetryTimes--
		task.Err = nil

		url = fmt.Sprintf("http://127.0.0.1:%d/metric", task.HTTPProfile)
		resp, task.Err = util.HTTPGetURLParams(url, nil, task.Logger)
		if task.Err != nil {
			time.Sleep(5 * time.Second)
			continue
		}
		break
	}
	if task.Err != nil {
		task.Err = fmt.Errorf("redis-shake错误退出")
		return nil
	}

	// redis 大版本大于7，使用的是redis-shakeV4
	if task.SrcBigVersion == 0 {
		task.GetSrcRedisVersion()
	}
	if task.SrcBigVersion >= getRedisShakeV4BeginVersion() {
		shakeMetric := RedisShakeV4Metric{}
		task.Err = json.Unmarshal(resp, &shakeMetric)
		if task.Err != nil {
			task.Err = fmt.Errorf("json.Unmarshal fail,err:%v,url:%s", task.Err, url)
			task.Logger.Error(task.Err.Error(), zap.String("resp", string(resp)))
			return nil
		}
		// 转换成低版本结构体返回
		reader := shakeMetric.Reader
		r := &RedisShakeMetric{
			Status: reader.Status,
		}
		if reader.Status == ShakeV4ReceiveDdbStatus {
			r.FullSyncProgress = 100 * reader.RdbReceivedBytes / reader.RdbFileSizeBytes
			r.FullSyncProgressHuman = fmt.Sprintf("[%s/%s]", reader.RdbReceivedHuman, reader.RdbFileSizeHuman)
		}
		if reader.Status == ShakeV4FullStatus {
			r.FullSyncProgress = 100 * reader.RdbSentBytes / reader.RdbFileSizeBytes
			r.FullSyncProgressHuman = fmt.Sprintf("[%s/%s]", reader.RdbSentHuman, reader.RdbFileSizeHuman)
		}
		if reader.Status == ShakeV4IncrStatus {
			r.Delay = fmt.Sprintf("%d bytes", reader.AofReceivedOffset-reader.AofSentOffset)
		}

		return r
	} else {
		shakeMeric := []RedisShakeMetric{}
		task.Err = json.Unmarshal(resp, &shakeMeric)
		if task.Err != nil {
			task.Err = fmt.Errorf("json.Unmarshal fail,err:%v,url:%s", task.Err, url)
			task.Logger.Error(task.Err.Error(), zap.String("resp", string(resp)))
			return nil
		}
		if len(shakeMeric) > 0 {
			return &shakeMeric[0]
		}
	}
	return nil
}

// 默认从7才开始使用redis-shake-v4
func getRedisShakeV4BeginVersion() int {
	beginVersion := viper.GetInt("redisShakeV4BeginVersion")
	if beginVersion == 0 {
		return 7
	}
	return beginVersion
}
