import yaml

with open("config.yml", 'r') as f:
    global conf
    conf = yaml.load(f)
