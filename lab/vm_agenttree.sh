#!/bin/sh
cd /opt/fim-agent && find agent -name "*.py" -exec sha256sum {} \; | sort -k2 | sha256sum
