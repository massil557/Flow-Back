import math

def lttb_downsample(points: list[dict], threshold: int) -> list[dict]:
    if threshold >= len(points) or threshold < 3:
        return points
    data = [{'x': p['time'].timestamp(), 'y': p['valeur']} for p in points]
    sampled = [points[0]]
    bucket_size = (len(data) - 2) / (threshold - 2)
    a = 0
    for i in range(0, threshold - 2):
        start = int(math.floor((i + 1) * bucket_size)) + 1
        end = int(math.floor((i + 2) * bucket_size)) + 1
        if end >= len(data):
            end = len(data) - 1
        count = end - start
        if count <= 0:
            count = 1
        avg_x = sum(d['x'] for d in data[start:end]) / count
        avg_y = sum(d['y'] for d in data[start:end]) / count
        max_area = -1
        next_idx = start
        for j in range(start, end):
            area = abs((data[a]['x'] - avg_x) * (data[j]['y'] - data[a]['y']) - (data[a]['x'] - data[j]['x']) * (avg_y - data[a]['y']))
            if area > max_area:
                max_area = area
                next_idx = j
        sampled.append(points[next_idx])
        a = next_idx
    sampled.append(points[-1])
    return sampled