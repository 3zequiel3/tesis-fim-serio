#!/bin/sh
cd /opt/fim-agent && find agent -name "*.py" ! -path "*/tests/*" | sort
