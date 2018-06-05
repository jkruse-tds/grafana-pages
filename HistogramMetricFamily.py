#!/usr/bin/python

import re
import time
import requests
import argparse
from pprint import pprint
import subprocess
import os
from sys import exit
from prometheus_client import start_http_server, Summary
from prometheus_client.core import HistogramMetricFamily, REGISTRY
import random
import time


DEBUG = int(os.environ.get('DEBUG', '0'))

COLLECTION_TIME = Summary('jenkins_collector_collect_seconds', 'Time spent to collect metrics from Jenkins')

class JenkinsCollector(object):
    # The build statuses we want to export about.
    statuses = ["lastBuild", "lastCompletedBuild", "lastFailedBuild",
                "lastStableBuild", "lastSuccessfulBuild", "lastUnstableBuild",
                "lastUnsuccessfulBuild"]

    def __init__(self, target, user, password, insecure):
        # Create a metric to track time spent and requests made.
        self.hist = HistogramMetricFamily('request_size', 'Time spent processing request', buckets=[['4096.0', 0], ['8192.0', 0], ['16384.0', 0], ['32768.0', 0], ['65536.0', 0], ['131072.0', 0], ['262144.0', 0], ['524288.0', 0], ['1048576.0', 0], ['2097152.0', 0], ["+Inf", 0]], sum_value=0)

        self._target = target.rstrip("/")
        self._user = user
        self._password = password
        self._insecure = insecure
        self._buckets = []
        self.count = 0

    def collect(self):
        start = time.time()

        h = HistogramMetricFamily('request_size', 'Time spent processing request', labels=["job", "pool"])
        # Request data from Jenkins
        self._request_data()
        self._buckets.append(["+Inf", 1])
        h.add_metric(labels=["zpool_writes", "t03_db"], buckets=self._buckets, sum_value=4096)
        yield h

        duration = time.time() - start
        COLLECTION_TIME.observe(duration)

    def _request_data(self):
        self._buckets = []
        self.count = self.count + 1
        bucket = ['4096.0', random.randint(10, 30)]
        self._buckets.append(bucket)
        bucket = ['8192.0', random.randint(50, 90)]
        self._buckets.append(bucket)
        bucket = ['16384.0', random.randint(90, 150)]
        self._buckets.append(bucket)
        bucket = ['32768.0', random.randint(10, 30)]
        self._buckets.append(bucket)
        bucket = ['65536.0', random.randint(2,10)]
        self._buckets.append(bucket)
        bucket = ['131072.0', random.randint(1,4)]
        self._buckets.append(bucket)
        if self.count == 10:
         bucket = ['2097152.0', 1]
         self._buckets.append(bucket)
         self.count = 0
        else:
         bucket = ['2097152.0', 0]
         self._buckets.append(bucket)
          

    def _setup_empty_prometheus_metrics(self):
        # The metrics we want to export.
        self._prometheus_metrics = {}
        for status in self.statuses:
            snake_case = re.sub('([A-Z])', '_\\1', status).lower()
            self._prometheus_metrics[status] = {
                'number':
                    GaugeMetricFamily('jenkins_job_{0}'.format(snake_case),
                                      'Jenkins build number for {0}'.format(status), labels=["jobname"]),
                'duration':
                    GaugeMetricFamily('jenkins_job_{0}_duration_seconds'.format(snake_case),
                                      'Jenkins build duration in seconds for {0}'.format(status), labels=["jobname"]),
                'timestamp':
                    GaugeMetricFamily('jenkins_job_{0}_timestamp_seconds'.format(snake_case),
                                      'Jenkins build timestamp in unixtime for {0}'.format(status), labels=["jobname"]),
                'queuingDurationMillis':
                    GaugeMetricFamily('jenkins_job_{0}_queuing_duration_seconds'.format(snake_case),
                                      'Jenkins build queuing duration in seconds for {0}'.format(status),
                                      labels=["jobname"]),
                'totalDurationMillis':
                    GaugeMetricFamily('jenkins_job_{0}_total_duration_seconds'.format(snake_case),
                                      'Jenkins build total duration in seconds for {0}'.format(status), labels=["jobname"]),
                'skipCount':
                    GaugeMetricFamily('jenkins_job_{0}_skip_count'.format(snake_case),
                                      'Jenkins build skip counts for {0}'.format(status), labels=["jobname"]),
                'failCount':
                    GaugeMetricFamily('jenkins_job_{0}_fail_count'.format(snake_case),
                                      'Jenkins build fail counts for {0}'.format(status), labels=["jobname"]),
                'totalCount':
                    GaugeMetricFamily('jenkins_job_{0}_total_count'.format(snake_case),
                                      'Jenkins build total counts for {0}'.format(status), labels=["jobname"]),
                'passCount':
                    GaugeMetricFamily('jenkins_job_{0}_pass_count'.format(snake_case),
                                      'Jenkins build pass counts for {0}'.format(status), labels=["jobname"]),
            }

    def _get_metrics(self, name, job):
        for status in self.statuses:
            if status in job.keys():
                status_data = job[status] or {}
                self._add_data_to_prometheus_structure(status, status_data, job, name)

    def _add_data_to_prometheus_structure(self, status, status_data, job, name):
        # If there's a null result, we want to pass.
        if status_data.get('duration', 0):
            self._prometheus_metrics[status]['duration'].add_metric([name], status_data.get('duration') / 1000.0)
        if status_data.get('timestamp', 0):
            self._prometheus_metrics[status]['timestamp'].add_metric([name], status_data.get('timestamp') / 1000.0)
        if status_data.get('number', 0):
            self._prometheus_metrics[status]['number'].add_metric([name], status_data.get('number'))
        actions_metrics = status_data.get('actions', [{}])
        for metric in actions_metrics:
            if metric.get('queuingDurationMillis', False):
                self._prometheus_metrics[status]['queuingDurationMillis'].add_metric([name], metric.get('queuingDurationMillis') / 1000.0)
            if metric.get('totalDurationMillis', False):
                self._prometheus_metrics[status]['totalDurationMillis'].add_metric([name], metric.get('totalDurationMillis') / 1000.0)
            if metric.get('skipCount', False):
                self._prometheus_metrics[status]['skipCount'].add_metric([name], metric.get('skipCount'))
            if metric.get('failCount', False):
                self._prometheus_metrics[status]['failCount'].add_metric([name], metric.get('failCount'))
            if metric.get('totalCount', False):
                self._prometheus_metrics[status]['totalCount'].add_metric([name], metric.get('totalCount'))
                # Calculate passCount by subtracting fails and skips from totalCount
                passcount = metric.get('totalCount') - metric.get('failCount') - metric.get('skipCount')
                self._prometheus_metrics[status]['passCount'].add_metric([name], passcount)


def parse_args():
    parser = argparse.ArgumentParser(
        description='jenkins exporter args jenkins address and port'
    )
    parser.add_argument(
        '-j', '--jenkins',
        metavar='jenkins',
        required=False,
        help='server url from the jenkins api',
        default=os.environ.get('JENKINS_SERVER', 'http://jenkins:8080')
    )
    parser.add_argument(
        '--user',
        metavar='user',
        required=False,
        help='jenkins api user',
        default=os.environ.get('JENKINS_USER')
    )
    parser.add_argument(
        '--password',
        metavar='password',
        required=False,
        help='jenkins api password',
        default=os.environ.get('JENKINS_PASSWORD')
    )
    parser.add_argument(
        '-p', '--port',
        metavar='port',
        required=False,
        type=int,
        help='Listen to this port',
        default=int(os.environ.get('VIRTUAL_PORT', '9118'))
    )
    parser.add_argument(
        '-k', '--insecure',
        dest='insecure',
        required=False,
        action='store_true',
        help='Allow connection to insecure Jenkins API',
        default=False
    )
    return parser.parse_args()


def main():
    try:
        args = parse_args()
        port = int(9990)
        REGISTRY.register(JenkinsCollector(args.jenkins, args.user, args.password, args.insecure))
        start_http_server(port)
        print("Polling {}. Serving at port: {}".format(args.jenkins, port))
        proc = subprocess.Popen(['python','-u', 'output.py'],stdout=subprocess.PIPE)
        while True:
          for line in proc.stdout.readline():
            if line != b'':
              os.write(1, line)

    except KeyboardInterrupt:
        print(" Interrupted")
        exit(0)


if __name__ == "__main__":
    main()

