# restate
Custom Flask-RESTful API that drives cloudless home automation

Currently drives the following automations:

|Endpoint|Description|
|---|---|
|`alert`|Forwards notifications to the python ntfy module|
|`tvcom`|Translates REST calls into serial commands to allow communication with an LG TV via a Bluetooth serial connection, [see here](https://github.com/kennedn/TvCom) for the companion project.|
|`snowdon`|Forwards REST calls on to a Majority Snowdon II soundbar modchip, [see here](https://github.com/kennedn/snowdon-ii-wifi) for the companion project.|
|`meross`|Transforms and forwards HTTP calls on to meross devices|
|`pc,shitcube`|Sends magic packets on to home computers to control the power state, [see here](https://github.com/kennedn/Action-On-LAN) for the companion project.|


## Pre-requisites 

### Kubernetes Cluster

In my case, I am running a microk8s instance on a Ubuntu 22.04 host machine.

### Bluetooth

The host must have a bluetooth controller attached to facilitate the `tvcom` endpoint.

Additionally the LG TV must have a Bluetooth UART device attached to its serial port, such as the [DSD SH-B23A](https://www.amazon.co.uk/DSD-TECH-SH-B23A-Bluetooth-Converter/dp/B07FP6NZB7/)

To allow the container to 'nab' the bluetooth device, bluez must be disabled on the host, this can be achieved on a systemd host machine by running:

```shell
sudo systemctl stop bluetooth  # Stop running process
sudo systemctl disable bluetooth # Disable from starting at boot
```

Finally, the bluetooth address and pin must be configured in the `deployment.yml` environment properties before deployment:
```yaml
---
            - name: "BT_ADDRESS"
              value: "00:14:03:05:0D:28"
            - name: "BT_PIN"
              value: "1234"
---
```

### Ntfy

To enable the `alert` endpoint, a ntfy configuration file must be placed at `config/ntfy.yml`. See the [official docs](https://ntfy.readthedocs.io/en/latest/#configuring-ntfy) for configuring a valid backend.


### Basic Auth

A basic auth token must be generated at the path config/htpasswd, this enables basic auth on the ingress controller for external clients and can be achieved with the following command:

```shell
sudo apt install apache2-utils
htpasswd -bc config/htpasswd USERNAME PASSWORD
```

## How to Deploy

Apply via kustomize:
`kubectl apply -k .`
