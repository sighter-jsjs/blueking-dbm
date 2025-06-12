/*
 * TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
 * Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
 * Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at https://opensource.org/licenses/MIT
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
 * an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations under the License.
 */

package backupexe

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/pkg/errors"
	"github.com/spf13/cast"

	"dbm-services/common/go-pubpkg/cmutil"
	"dbm-services/mysql/db-tools/mysql-dbbackup/pkg/config"
	"dbm-services/mysql/db-tools/mysql-dbbackup/pkg/cst"
	"dbm-services/mysql/db-tools/mysql-dbbackup/pkg/src/dbareport"
	"dbm-services/mysql/db-tools/mysql-dbbackup/pkg/src/logger"
	"dbm-services/mysql/db-tools/mysql-dbbackup/pkg/util"
)

// LogicalDumper TODO
type LogicalDumper struct {
	cnf             *config.BackupConfig
	dbbackupHome    string
	backupStartTime time.Time
	backupEndTime   time.Time
}

func (l *LogicalDumper) initConfig(mysqlVerStr string, logBinDisabled bool) error {
	if l.cnf == nil {
		return errors.New("logical dumper params is nil")
	}
	if cmdPath, err := os.Executable(); err != nil {
		return err
	} else {
		l.dbbackupHome = filepath.Dir(cmdPath)
	}
	BackupTool = cst.ToolMydumper
	return nil
}

// Execute excute dumping backup with logical backup tool
func (l *LogicalDumper) Execute(ctx context.Context) error {
	l.backupStartTime = time.Now()
	defer func() {
		l.backupEndTime = time.Now()
	}()
	binPath := filepath.Join(l.dbbackupHome, "/bin/mydumper")
	args := []string{
		"-h", l.cnf.Public.MysqlHost,
		"-P", strconv.Itoa(l.cnf.Public.MysqlPort),
		"-u", l.cnf.Public.MysqlUser,
		"-p", l.cnf.Public.MysqlPasswd,
		"-o", filepath.Join(l.cnf.Public.BackupDir, l.cnf.Public.TargetName()),
		"--long-query-retry-interval=10",
		fmt.Sprintf("--long-query-retries=%d", l.cnf.LogicalBackup.FlushRetryCount),
		fmt.Sprintf("--set-names=%s", l.cnf.Public.MysqlCharset),
		fmt.Sprintf("--chunk-filesize=%d", l.cnf.LogicalBackup.ChunkFilesize),
		fmt.Sprintf("--threads=%d", l.cnf.LogicalBackup.Threads),
		// "--disk-limits=1GB:5GB",
	}
	if l.cnf.LogicalBackup.TrxConsistencyOnly != nil && *l.cnf.LogicalBackup.TrxConsistencyOnly {
		args = append(args, "--trx-consistency-only")
	}
	if l.cnf.Public.KillLongQueryTime > 0 {
		args = append(args, "--kill-long-queries",
			fmt.Sprintf("--long-query-guard=%d", l.cnf.Public.KillLongQueryTime))
	} else {
		if l.cnf.Public.FtwrlWaitTimeout > 0 {
			args = append(args, fmt.Sprintf("--long-query-guard=%d", l.cnf.Public.FtwrlWaitTimeout))
		} else {
			args = append(args, "--long-query-guard=999999") // 不退出
		}
	}
	if l.cnf.Public.AcquireLockWaitTimeout > 0 {
		if ok, _ := MydumperHasOption(binPath, "--lock-wait-timeout", "1"); ok {
			args = append(args, fmt.Sprintf("--lock-wait-timeout=%d", l.cnf.Public.AcquireLockWaitTimeout))
		} else {
			logger.Log.Warn("mydumper has no option. ignore", "--lock-wait-timeout")
		}
	}
	if !l.cnf.LogicalBackup.DisableCompress {
		args = append(args, "--compress")
	}
	if l.cnf.LogicalBackup.DefaultsFile != "" {
		args = append(args, []string{
			fmt.Sprintf("--defaults-file=%s", l.cnf.LogicalBackup.DefaultsFile),
		}...)
	}
	if tableFilter, err := l.cnf.LogicalBackup.BuildArgsTableFilterForMydumper(); err != nil {
		return err
	} else {
		args = append(args, tableFilter...)
	}

	if l.cnf.Public.DataSchemaGrant == "" {
		if l.cnf.LogicalBackup.NoData {
			args = append(args, "--no-data")
		}
		if l.cnf.LogicalBackup.NoSchemas {
			args = append(args, "--no-schemas")
		}
		if l.cnf.LogicalBackup.Events {
			args = append(args, "--events")
		}
		if l.cnf.LogicalBackup.Routines {
			args = append(args, "--routines")
		}
		if l.cnf.LogicalBackup.Triggers {
			args = append(args, "--triggers")
		}
		if l.cnf.LogicalBackup.InsertMode == "replace" {
			args = append(args, "--replace")
		} else if l.cnf.LogicalBackup.InsertMode == "insert_ignore" {
			args = append(args, "--insert-ignore")
		}
	} else {
		if l.cnf.Public.IfBackupSchema() && !l.cnf.Public.IfBackupData() {
			args = append(args, []string{
				"--no-data", "--events", "--routines", "--triggers",
			}...)
		} else if !l.cnf.Public.IfBackupSchema() && l.cnf.Public.IfBackupData() {
			args = append(args, []string{
				"--no-schemas", "--no-views",
			}...)
		} else if l.cnf.Public.IfBackupSchema() && l.cnf.Public.IfBackupData() {
			args = append(args, []string{
				"--events", "--routines", "--triggers",
			}...)
		}
	}
	if l.cnf.LogicalBackup.ExtraOpt != "" {
		args = append(args, l.cnf.LogicalBackup.ExtraOpt)
	}

	var cmd *exec.Cmd
	cmd = exec.CommandContext(ctx, "sh", "-c", fmt.Sprintf(`%s %s`, binPath, strings.Join(args, " ")))
	logger.Log.Info("logical dump command: ", cmd.String())

	mydumperLogFile := filepath.Join(logger.GetLogDir(),
		fmt.Sprintf("mydumper_%d_%d.log", l.cnf.Public.MysqlPort, int(time.Now().Weekday())))
	outFile, err := os.OpenFile(mydumperLogFile, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0644)
	if err != nil {
		logger.Log.Error("create log file failed: ", err)
		return err
	}
	defer func() {
		_ = outFile.Close()
	}()

	cmd.Stdout = outFile
	cmd.Stderr = outFile

	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setpgid: true,
	}

	if err = cmd.Start(); err != nil {
		return err
	}

	sig := make(chan os.Signal)
	signal.Notify(sig, syscall.SIGHUP, syscall.SIGINT, syscall.SIGTERM, syscall.SIGQUIT) // syscall.SIGKILL
	go func() {
		select {
		case s := <-sig:
			logger.Log.Warnf("dbbackup got signal: %v", s)
			if cmd.Process != nil {
				err := cmd.Process.Kill() // syscall.Kill(-cmd.Process.Pid,syscall.SIGKILL)
				logger.Log.Warnf("kill mydumper %d exit with %v", cmd.Process.Pid, err)
			}
		}
	}()

	err = cmd.Wait()
	if err != nil {
		// mydumper 的错误信息要从头往后看，看最近的日志因为多线程的原因，不准确
		errStrPrefix := fmt.Sprintf("head 5 error from %s", mydumperLogFile)
		errStrDetail, _ := cmutil.NewGrepLines(mydumperLogFile, true, true).
			MatchWords([]string{"ERROR", "CRITICAL", "fatal", "No such file"}, 5)
		if len(errStrDetail) > 0 {
			logger.Log.Info(errStrPrefix)
			logger.Log.Error(errStrDetail)
		} else {
			logger.Log.Warn("can not find more detail error message from ", mydumperLogFile)
		}
		logger.Log.Error("run logical backup failed ", err, l.cnf.Public.MysqlPort)
		return errors.WithMessagef(err, fmt.Sprintf("%s\n%s", errStrPrefix, errStrDetail))
	}
	// check the integrity of backup
	integrityErr := util.CheckIntegrity(&l.cnf.Public)
	if integrityErr != nil {
		logger.Log.Error("Failed to check the integrity of backup, error: ", integrityErr)
		return integrityErr
	}
	return nil
}

// PrepareBackupMetaInfo prepare the backup result of Logical Backup
// mydumper 备份完成后，解析 metadata 文件
func (l *LogicalDumper) PrepareBackupMetaInfo(cnf *config.BackupConfig, metaInfo *dbareport.IndexContent) error {
	if metaInfo.BinlogInfo.ShowSlaveStatus == nil {
		metaInfo.BinlogInfo.ShowSlaveStatus = &dbareport.StatusInfo{}
	}
	if metaInfo.BinlogInfo.ShowMasterStatus == nil {
		metaInfo.BinlogInfo.ShowMasterStatus = &dbareport.StatusInfo{}
	}
	metaFileName := filepath.Join(cnf.Public.BackupDir, cnf.Public.TargetName(), "metadata")
	metadata, err := parseMydumperMetadata(metaFileName)
	if err != nil {
		return errors.WithMessage(err, "parse mydumper metadata")
	}
	logger.Log.Infof("metadata file:%+v", metadata)
	metaInfo.BackupBeginTime, err = time.ParseInLocation(cst.MydumperTimeLayout, metadata.DumpStarted, time.Local)
	if err != nil {
		return errors.Wrapf(err, "parse BackupBeginTime %s", metadata.DumpStarted)
	}
	metaInfo.BackupEndTime, err = time.ParseInLocation(cst.MydumperTimeLayout, metadata.DumpFinished, time.Local)
	if err != nil {
		return errors.Wrapf(err, "parse BackupEndTime %s", metadata.DumpFinished)
	}
	metaInfo.BackupConsistentTime = metaInfo.BackupBeginTime // 逻辑备份开始时间认为是一致性位点时间
	metaInfo.BinlogInfo.ShowMasterStatus = &dbareport.StatusInfo{
		BinlogFile: metadata.MasterStatus["File"],
		BinlogPos:  metadata.MasterStatus["Position"],
		Gtid:       metadata.MasterStatus["Executed_Gtid_Set"],
		MasterHost: cnf.Public.MysqlHost, // use backup_host as local binlog file_pos host
		MasterPort: cast.ToInt(cnf.Public.MysqlPort),
	}
	if strings.ToLower(cnf.Public.MysqlRole) == cst.RoleSlave {
		metaInfo.BinlogInfo.ShowSlaveStatus = &dbareport.StatusInfo{
			BinlogFile: metadata.SlaveStatus["Relay_Master_Log_File"],
			BinlogPos:  metadata.SlaveStatus["Exec_Master_Log_Pos"],
			Gtid:       metadata.SlaveStatus["Executed_Gtid_Set"],
			MasterHost: metadata.SlaveStatus["Master_Host"],
			MasterPort: cast.ToInt(metadata.SlaveStatus["Master_Port"]),
		}
	}
	metaInfo.JudgeIsFullBackup(&cnf.Public)

	return nil
}

// MydumperHasOption check mydumper has --xxx or not
// example: ./mydumper --lock-wait-timeout 1 --help
func MydumperHasOption(bin string, option ...string) (bool, error) {
	// --help 在前/后 无所谓
	cmdArgs := []string{bin, "--help"}
	cmdArgs = append(cmdArgs, option...)
	_, cmdStderr, err := cmutil.ExecCommand(false, "", cmdArgs[0], cmdArgs[1:]...)
	if err == nil {
		return true, nil
	}
	if strings.Contains(cmdStderr, "Unknown option") {
		return false, nil
	} else {
		return false, err
	}
}
