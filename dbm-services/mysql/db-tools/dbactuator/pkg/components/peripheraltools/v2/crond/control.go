package crond

import (
	"dbm-services/common/go-pubpkg/cmutil"
	"fmt"
	"os/exec"
	"os/user"
	"path"
	"path/filepath"

	"github.com/pkg/errors"

	"dbm-services/common/go-pubpkg/logger"
	"dbm-services/mysql/db-tools/dbactuator/pkg/core/cst"
	"dbm-services/mysql/db-tools/dbactuator/pkg/util/osutil"
)

func Stop() (err error) {
	var cmd *exec.Cmd

	cu, _ := user.Current()
	if cu.Uid == "0" {
		cmd = exec.Command(
			"su", []string{
				"-", "mysql", "-c",
				fmt.Sprintf(
					`/bin/sh %s`,
					path.Join(cst.MySQLCrondInstallPath, "stop.sh"),
				),
			}...,
		)
	} else {
		cmd = exec.Command(
			"sh", "-c", filepath.Join(cst.MySQLCrondInstallPath, "stop.sh"),
		)
	}

	err = cmd.Run()
	if err != nil {
		logger.Error("stop mysql-crond failed: %s", err.Error())
		return err
	}
	logger.Info("stop mysql-crond success")
	return nil
}

func Start() (err error) {
	chownCmd := fmt.Sprintf(`chown -R mysql %s`, cst.MySQLCrondInstallPath)
	_, err = osutil.ExecShellCommand(false, chownCmd)
	if err != nil {
		logger.Error("chown %s to mysql failed: %s", cst.MySQLCrondInstallPath, err.Error())
		return err
	}

	cmd := exec.Command(
		"su", []string{
			"-", "mysql", "-c", // mysql 写死
			fmt.Sprintf(
				`%s -c %s`,
				path.Join(cst.MySQLCrondInstallPath, "start.sh"),
				path.Join(cst.MySQLCrondInstallPath, "runtime.yaml"),
			),
		}...,
	)
	err = cmd.Run()
	if err != nil {
		logger.Error("start mysql-crond failed: %s", err.Error())

		startErrFilePath := path.Join(cst.MySQLCrondInstallPath, "start-crond.err")
		errStrPrefix := fmt.Sprintf("grep error from %s", startErrFilePath)
		errStrDetail, _ := cmutil.NewGrepLines(startErrFilePath, true, true).MatchWords(
			[]string{"ERROR", "panic"}, 5)
		if len(errStrDetail) > 0 {
			logger.Info(errStrPrefix)
			logger.Error(errStrDetail)
		} else {
			logger.Warn("tail can not find more detail error message from ", startErrFilePath)
		}
		return errors.WithMessagef(err, fmt.Sprintf("%s\n%s", errStrPrefix, errStrDetail))
	}

	logger.Info("mysql-crond started")
	return nil
}
