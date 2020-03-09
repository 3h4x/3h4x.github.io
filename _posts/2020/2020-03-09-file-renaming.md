---
layout: post
title:  "Mass file renaming containing nonASCII characters to ASCII"
categories: tech
tags: [tools]
comments: True
---
Recently I found a problem with playing samba resources with VLC. Polish characters were breaking playback because
file could not be found. Strangely enough this happened only for files with lowercase Polish letters like `ąśżźćłóęń`.  
Removing those letters helped to fix playback on test file but I had more than one file to fix.

I tried to find a way to do rename all files quickly and easy and get rid of nonASCII characters and in this post I'm
providing easiest, quickest and robust way to this.

<!-- readmore -->

## Meet rename
`rename` - This program renames files according to modification rules specified on the command line. If no filenames are given on the command line, a list of filenames will be expected on
       standard input.
       
{% highlight shell %}
Usage:
    rename [switches|transforms] [files]

    Switches:

    --man (read the full manual)
    -0/--null (when reading from STDIN)
    -f/--force or -i/--interactive (proceed or prompt when overwriting)
    -g/--glob (expand "*" etc. in filenames, useful in Windows™ CMD.EXE)
    -k/--backwards/--reverse-order
    -l/--symlink or -L/--hardlink
    -M/--use=*Module*
    -n/--just-print/--dry-run
    -N/--counter-format
    -p/--mkpath/--make-dirs
    --stdin/--no-stdin
    -t/--sort-time
    -T/--transcode=*encoding*
    -v/--verbose

    Transforms, applied sequentially:

    -a/--append=*str*
    -A/--prepend=*str*
    -c/--lower-case
    -C/--upper-case
    -d/--delete=*str*
    -D/--delete-all=*str*
    -e/--expr=*code*
    -P/--pipe=*cmd*
    -s/--subst *from* *to*
    -S/--subst-all *from* *to*
    -x/--remove-extension
    -X/--keep-extension
    -z/--sanitize
    --camelcase --urlesc --nows --rews --noctrl --nometa --trim (see manual)
{% endhighlight %}

A lot of flags but one of them is especially useful `-e/--expr`. This allow us to use regex to rename files.  
Exactly what I was looking for.  
So for example using:
`-e 's/ż|Ż/Z/'` will replace lowercase and uppercase `ź` with just `Z`. 

You can imagine the same can be done for Czech language or Chinese.

### Snippets

- Change lowercase Polish characters to uppercase.
{% highlight shell %}
rename \
-e 's/ś/Ś/' \
-e 's/ą/Ą/' \
-e 's/ż/Ż/' \
-e 's/ź/Ź/' \
-e 's/ł/Ł/' \
-e 's/ó/Ó/' \
-e 's/ę/Ę/' \
-e 's/ń/Ń/' \
-e 's/ć/Ć/' \
*
{% endhighlight %}
- Rename all files in current dir so they don't have Polish characters. 
{% highlight shell %}
rename \
-e 's/ś|Ś/S/' \
-e 's/ą|Ą/A/' \
-e 's/ż|Ż/Z/' \
-e 's/ź|Ź/Z/' \
-e 's/ł|Ł/L/' \
-e 's/ó|Ó/O/' \
-e 's/ę|Ę/E/' \
-e 's/ń|Ń/N/' \
-e 's/ć|Ć/C/' \
*
{% endhighlight %}

- Remove all Polish characters from files in current directory.

{% highlight shell %}
rename \
-e 's/ś|Ś|ą|Ą|ż|Ż|ź|Ź|ł|Ł|ó|Ó|ę|Ę|ń|Ń|ć|Ć//g' \
*
{% endhighlight %}


3h4x
