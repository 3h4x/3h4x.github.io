---
layout: post
title:  "Hello world and Dell Latitude E5440 configuration"
date:   2015-01-10 18:55:32
categories: configuration
comments: True
---
## Hello world!
YAB is on the web. I had hard time picking right technology, what I wanted is blog as simple as it can get.
At the end of the day Jekyll won over chirp and octopress.

`exit 0`

Installation of Jessie left me with two problems and right after that I want to restore my default setup.
To the point!

## Two problems with my Dell

* WiFi not working.

    Let's check what we have:

    `lspci`

    `02:00.0 Network controller: Intel Corporation Wireless 7260 (rev 73)`

    To fix it you need drivers that are in non-free packages.

    `sudo sed -i.bak 's/main contrib/main contrib non-free/' /etc/apt/sources.list'`
    `sudo aptitude update && sudo aptitude install firmware-iwlwifi`

* CPU freaks out after waking up from sleep.

    Let's go!

    `sudo aptitude install cpufreqd cpufrequtils`

## Automate all the things!
I use puppet but I don't want to start flame war.

Some of the stuff is puppet code but of course I need to restore some files too like autofs, sudoers, hosts, etc..
I have divided my setup to sections, you can save code to file such as 'awesome.pp' and then execute it with
`puppet apply awesome.pp`

* Install my favourite packages
{% highlight ruby %}
  @package { [
  'cron-apt',
  'bzip2',
  'tar',
  'python-ldap',
  'ldap-utils',
  'sudo',
  'build-essential',
  'curl',
  'git-core',
  'openssh-server',
  'sysstat',
  'iotop',
  'multitail',
  'tcpdump',
  'dnsutils',
  'diffutils',
  'screen',
  'htop',
  'git',
  'mtr-tiny',
  'augeas-tools',
  'gnome-shell',
  'gnome-terminal',
  'network-manager-openvpn-gnome',
  'docker.io',
  'vagrant',
  'pidgin',
  'git-flow',
  'autofs',
  ]: ensure => installed }

  Package <| |>
{% endhighlight %}
* Firefox installation
{% highlight bash %}
#!/bin/bash
puppet module install h4x-firefox
puppet apply -e "include firefox"
{% endhighlight %}
* Configure VIM
{% highlight ruby %}
  @package { [
  'vim',
  'vim-addon-manager',
  'vim-ruby',
  'vim-puppet',
  'vim-python',
  'vim-latexsuite',
  ]: ensure => installed }
  Package <| |>

  exec { 'vim-addons install -w latex-suite':
    path    => ['/usr/bin/', '/bin', ],
    unless  => "vim-addons | grep latex-suite | awk '{ print $3 }' | grep installed",
    require => Package['vim-latexsuite'],
  }
  exec { 'vim-addons install -w puppet':
    path    => ['/usr/bin/', '/bin', ],
    unless  => "vim-addons | grep puppet | awk '{ print $3 }' | grep installed",
    require => Package['vim-puppet'],
  }

{% endhighlight %}
* Custom bash prompt
{% highlight ruby %}
  exec { '/usr/bin/git clone https://github.com/magicmonty/bash-git-prompt.git':
    cwd     => '/opt',
    unless  => '/usr/bin/file -d /opt/bash-git-prompt/',
    require => Package['git'],
  } ->
  exec { '/bin/echo "source /opt/bash-git-prompt/gitprompt.sh" >> /etc/bash.bashrc':
    unless => "/bin/grep 'source /opt/bash-git-prompt/gitprompt.sh' /etc/bash.bashrc",
  }
{% endhighlight %}

These are all snippets of code, but man they come real handy when you want your default configuration on laptop :)

Treat your configuration as code, make everything volatile and stop worrying about tomorrow!

> Bye bye, see you real soon!

3hx