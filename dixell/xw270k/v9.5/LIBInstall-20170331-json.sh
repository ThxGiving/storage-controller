#!/bin/sh

export PATH=/usr/local/bin:/usr/bin:/bin:$PATH
LOG=/opt/log/LibUpdate.log
TYPE=$1

if [ -e "$LOG" ]; then
    mv $LOG ${LOG}_bkp
fi

_log(){
    echo `date +%F_%H%M%S`"-- $1" >> $LOG
}

_get_current_version(){
    local FNAME=$(basename `ls /opt/xweb/XWEB_EVO*`)
    echo $FNAME|grep tag>/dev/null
    ECODE=$?
    if [ "$ECODE" -eq "0" ]; then
	local V=$(echo $FNAME|cut -d "_" -f 7)
    else
	local V=$(echo $FNAME|cut -d "_" -f 6)
    fi
    echo $V
}

V=$(_get_current_version)
_log "Detected version: $V -- $TYPE"
echo $V|grep "-" > /dev/null
ECODE=$?
if [ "$ECODE" -eq "0" ]; then
    VN=$(echo $V|cut -d"-" -f 1)
    if [ "$TYPE" == "json" ]; then
	if [ "$VN" \< "2.0.0" ]; then
	    _log "Trying ot install $TYPE package on 1.0.x version -- Aborting"
	    rm -f /opt/backup/LIBPackage.tar.gz
	    exit 1
	fi
    else
	if [ "$VN" \> "1.9.0" ]; then
	    _log "Trying ot install $TYPE package on 2.0.x or above version -- Aborting"
	    rm -f /opt/backup/LIBPackage.tar.gz
	    exit 2
	fi
    fi
else
    _log "Skipping TYPE control because of development version"
fi

find /opt/xweb/sysdb/partab -type f -iname 'partab.default' -exec rm -f {} \;
_log "Extracting ${TYPE} libraries..."
tar -xzf /opt/backup/LIBPackage.tar.gz -C /opt/xweb/sysdb
_log "Adjusting ownership and permissions..."
chown -R root.root /opt/xweb/sysdb
chmod -R 0755 /opt/xweb/sysdb
_log "Removing package..."
rm -f /opt/backup/LIBPackage.tar.gz
if [ -e /opt/xweb/sysdb/models/dixell/EnumResType.sqlite ]; then
    _log "Removing unused EnumResType.sqlite..."
    rm -f /opt/xweb/sysdb/models/dixell/EnumResType.sqlite
fi

if [ "$TYPE" == "json" ]; then
    if [ -e /opt/xweb/bin/tools/createLibrariesList.lua ]; then
        _log "Updating libraries list"
        /opt/xweb/bin/tools/createLibrariesList.lua
    fi
    cd /opt/xweb/sysdb
    FLIST=$(cat deployed_libs_json)
    for F in $FLIST
    do
	RM_F_NAME=${F}/model_$(basename $F).sqlite
	_log "Removing $RM_F_NAME library..."
	rm -f $RM_F_NAME
    done
    cd -
fi
