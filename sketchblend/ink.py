"""Architectural print treatments for the Blender 5.3 render compositor."""

import bpy

__all__ = ('INK_VARIANTS', 'install_ink')

INK_VARIANTS = (
    'LINES_ONLY', 'LINE_WHITE', 'LINE_TONE', 'COLOR_LINE_TONE',
    'BLUEPRINT', 'HALFTONE', 'SKETCH_STYLE', 'SKETCHY_LINES', 'SKETCHY_COLOR',
    'SKETCHY_SHADED', 'COMIC_STYLE', 'COZY_INK',
)

_PAPER = (.98, .965, .92, 1)
_INK = (.012, .017, .022, 1)


class _Graph:
    def __init__(self, tree):
        self.tree = tree
        self.column = -1

    def stage(self, title):
        self.column += 1
        self.row = 0
        self.frame = self.tree.nodes.new('NodeFrame')
        self.frame.label = title
        self.frame.location = (460 * self.column, 0)

    def node(self, kind, **inputs):
        n = self.tree.nodes.new(kind)
        n.parent = self.frame
        n.location = (0, -210 * self.row)
        self.row += 1
        for key, value in inputs.items():
            self.set(n.inputs[key], value)
        return n

    def set(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        else:
            socket.default_value = value

    def math(self, op, a, b=0, *, clamp=False, label=''):
        n = self.node('ShaderNodeMath')
        n.operation, n.use_clamp, n.label = op, clamp, label
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        return n.outputs[0]

    def vector(self, op, a, b):
        n = self.node('ShaderNodeVectorMath')
        n.operation = op
        self.set(n.inputs[0], a)
        self.set(n.inputs['Scale' if op == 'SCALE' else 1], b)
        return n.outputs['Value' if op == 'DISTANCE' else 'Vector']

    def mix(self, factor, a, b):
        n = self.node('ShaderNodeMixRGB')
        for socket, value in zip(n.inputs, (factor, a, b)):
            self.set(socket, value)
        return n.outputs[0]

    def ramp(self, value, low, high, label=''):
        n = self.node('ShaderNodeMapRange')
        n.clamp = True
        n.label = label
        for key, v in (('Value', value), ('From Min', low), ('From Max', high)):
            self.set(n.inputs[key], v)
        return n.outputs[0]

    def sobel(self, value):
        return self.node('CompositorNodeFilter', Image=value, Type='Sobel').outputs[0]

    def shift(self, value, x, y):
        return self.node('CompositorNodeTranslate', Image=value, X=x, Y=y,
                         **{'Extension X': 'Extend', 'Extension Y': 'Extend'}).outputs[0]


def _contours(g, layers, luma, variant):
    cozy = variant == 'COZY_INK'
    comic = variant == 'COMIC_STYLE'
    # Depth is logarithmic so the cutoff is a relative depth jump. Cap the sky
    # sentinel before filtering. Normal differences catch untextured creases.
    g.stage('Depth breaks')
    depth = g.math('MINIMUM', layers['Depth'], 1e6)
    depth = g.math('LOGARITHM', g.math('MAXIMUM', depth, .001), 2)
    depth_edge = g.ramp(g.sobel(depth), .25 if cozy else .12, .86 if cozy else .66,
                        'Reject gradual perspective slope')
    g.stage('Creases and silhouettes')
    normal = layers['Normal']
    # Compare full signed vectors, rather than converting normals to luminance.
    nx = g.vector('DISTANCE', normal, g.shift(normal, 1, 0))
    ny = g.vector('DISTANCE', normal, g.shift(normal, 0, 1))
    crease = g.ramp(g.math('MAXIMUM', nx, ny), .34 if cozy else .24, .93 if cozy else .83)
    g.stage('Lighting and material detail')
    detail = g.ramp(g.sobel(luma), .10, .46, 'Reject weak texture gradients')
    detail = g.math('MULTIPLY', detail, .08 if cozy else (.80 if comic else .62))
    detail.node.name = 'SB Detail strength'
    # Remove depth breaks from the crease seed, before expanding either stroke.
    interior = g.math('SUBTRACT', 1, g.ramp(depth_edge, .04, .42))
    crease = g.math('MULTIPLY', crease, interior)
    g.stage('Independent stroke widths')
    sil_width = g.node('CompositorNodeDilateErode', Mask=depth_edge, Size=int(comic))
    sil_width.name = 'SB Silhouette width'
    crease_width = g.node('CompositorNodeDilateErode', Mask=crease, Size=0)
    crease_width.name = 'SB Crease width'
    depth_edge = g.math('MULTIPLY', sil_width.outputs[0], 1, clamp=True)
    depth_edge.node.name = 'SB Depth strength'
    crease = g.math('MULTIPLY', crease_width.outputs[0], .68 if cozy else .85, clamp=True)
    crease.node.name = 'SB Crease strength'
    # Composite independent coverages. A stronger overlapping mask must not
    # completely hide changes to another stroke, as MAXIMUM did.
    remaining = g.math('MULTIPLY', g.math('SUBTRACT', 1, depth_edge),
                       g.math('SUBTRACT', 1, crease))
    return g.math('SUBTRACT', 1, g.math('MULTIPLY', remaining,
                                       g.math('SUBTRACT', 1, detail, clamp=True)))


def _dots(g, coords, luma):
    g.stage('45° halftone screen · 7 px')
    x, y = g.node('ShaderNodeSeparateXYZ', Vector=coords).outputs[:2]
    u = g.math('ADD', x, y)
    v = g.math('SUBTRACT', x, y)

    def centered_square(axis):
        period = g.math('DIVIDE', axis, 9.90)
        period.node.name = 'SB Dot period' if axis == u else 'SB Dot period V'
        phase = g.math('FRACT', period)
        center = g.math('SUBTRACT', phase, .5)
        return g.math('MULTIPLY', center, center)

    radius = g.math('POWER', g.math('ADD', centered_square(u), centered_square(v)), .5)
    darkness = g.ramp(luma, .16, .83)
    size = g.math('MULTIPLY', g.math('SUBTRACT', 1, darkness), .54)
    distance = g.math('SUBTRACT', size, radius)
    return g.ramp(distance, .005, .15, 'Soft dot boundary')


def _pencil(g, coords, shade, edge, strong):
    g.stage('Graphite pressure and offset strokes')
    noise = g.node('ShaderNodeTexNoise', Vector=coords, Scale=.22, Detail=2).outputs[0]
    pressure = g.ramp(noise, .22, .78)
    ghost = g.math('MULTIPLY', g.shift(edge, -1.5, 1), .35)
    stroke = g.math('MAXIMUM', edge, ghost)
    stroke = g.math('MULTIPLY', stroke, g.math('ADD', .34, g.math('MULTIPLY', pressure, .60 if strong else .42)))
    g.stage('Diagonal pencil hatching')
    x, y = g.node('ShaderNodeSeparateXYZ', Vector=coords).outputs[:2]
    diagonal = g.math('ADD', x, g.math('MULTIPLY', y, 1.6))
    diagonal = g.math('ADD', diagonal, g.math('MULTIPLY', noise, 3.0))
    phase = g.math('FRACT', g.math('DIVIDE', diagonal, 10))
    hatch = g.math('SUBTRACT', 1, g.ramp(phase, .07, .27))
    hatch = g.math('MULTIPLY', hatch, g.math('SUBTRACT', 1, g.ramp(shade, .14, .58)))
    hatch = g.math('MULTIPLY', hatch, .34 if strong else .21, clamp=True)
    hatch.node.name = 'SB Hatch strength'
    return g.math('MAXIMUM', stroke, hatch)


def _build(tree, scene, layer, variant):
    g = _Graph(tree)
    g.stage('Rendered scene')
    render = g.node('CompositorNodeRLayers')
    render.scene = scene
    render.layer = layer.name
    layers = render.outputs
    # Premultiplied transparent areas print on paper instead of becoming solid ink.
    alpha_over = g.node('CompositorNodeAlphaOver')
    # Alpha Over's 5.3 socket names distinguish foreground and background.
    g.set(alpha_over.inputs['Background'], _PAPER)
    g.set(alpha_over.inputs['Foreground'], layers['Image'])
    image = alpha_over.outputs[0]
    bw = g.node('CompositorNodeRGBToBW')
    g.set(bw.inputs[0], image)
    luma = bw.outputs[0]
    shade = g.math('POWER', g.math('MAXIMUM', luma, 0), .5, label='Perceptual value')
    comic = variant == 'COMIC_STYLE'
    edge = _contours(g, layers, shade, variant)
    coord = None
    if variant in {'HALFTONE', 'COMIC_STYLE'} or variant.startswith('SKETCH'):
        g.stage('Screen-space coordinates')
        coord = g.node('CompositorNodeImageCoordinates', Image=image).outputs['Pixel']
    if variant.startswith('SKETCH'):
        edge = _pencil(g, coord, shade, edge, variant != 'SKETCH_STYLE')
    if variant in {'HALFTONE', 'COMIC_STYLE'}:
        dots = g.math('MULTIPLY', _dots(g, coord, shade), 1, clamp=True)
        dots.node.name = 'SB Screen strength'

    g.stage('Print palette')
    paper, ink = _PAPER, _INK
    if variant == 'COZY_INK':
        ink = (.038, .023, .021, 1)
        wash = g.node('CompositorNodeHueSat', Image=image, Saturation=1.15)
        paper = g.mix(.025, wash.outputs['Image'], _PAPER)
    elif variant == 'BLUEPRINT':
        paper = g.mix(g.ramp(shade, .11, .93), (.012, .028, .085, 1), (.029, .067, .173, 1))
        ink = (.34, .65, .97, 1)
    elif variant == 'LINES_ONLY':
        paper = (1, 1, 1, 1)
    elif variant == 'LINE_WHITE':
        paper = g.mix(g.ramp(shade, .08, .86), (.77, .75, .70, 1), _PAPER)
    elif variant in {'LINE_TONE', 'COLOR_LINE_TONE', 'COMIC_STYLE'}:
        step = .24 if comic else .16
        band = g.math('SNAP', g.math('ADD', shade, step / 2), step)
        if variant == 'COLOR_LINE_TONE':
            ratio = g.math('DIVIDE', band, g.math('MAXIMUM', shade, .025))
            gain = g.math('MINIMUM', g.math('POWER', ratio, 2), 1.65)
            paper = g.mix(.095, g.vector('SCALE', image, gain), _PAPER)
        else:
            value = g.math('POWER', g.ramp(band, .10, .88), 2.2 if comic else 1.65)
            paper = g.mix(value, (.009, .010, .013, 1) if comic else (.035, .038, .04, 1), _PAPER)
        if comic:
            paper = g.mix(g.math('MULTIPLY', dots, .67), paper, ink)
    elif variant == 'HALFTONE':
        paper = g.mix(dots, _PAPER, (.035, .042, .053, 1))
    elif variant == 'SKETCHY_COLOR':
        paper = g.mix(.38, image, _PAPER)
    elif variant in {'SKETCH_STYLE', 'SKETCHY_SHADED'}:
        paper = g.mix(g.ramp(shade, .08, .91), (.40, .39, .36, 1), _PAPER)
        if variant == 'SKETCH_STYLE':
            ink = (.16, .15, .13, 1)

    tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    edge = g.math('MULTIPLY', edge, .86 if variant == 'COZY_INK' else (.88 if comic else 1), clamp=True)
    edge.node.name = 'SB Ink strength'
    surface = g.mix(0, paper, image)
    surface.node.name = 'SB Material color mix'
    result = g.mix(edge, surface, ink)
    result.node.name = 'SB Ink color'
    output = g.node('NodeGroupOutput')
    g.set(output.inputs['Image'], result)


def install_ink(scene, variant):
    """Install a print compositor and return its node tree.

    Variant names are case insensitive; spaces/hyphens can replace underscores.
    Uses the current enabled view layer where possible. Replaces the compositor without editing the previous
    tree, objects, materials, lighting, or output paths. Pass a separate scene
    copy to keep the original scene settings.
    """
    key = variant.strip().upper().replace('-', '_').replace(' ', '_') if isinstance(variant, str) else None
    if key not in INK_VARIANTS:
        raise ValueError(f'Unknown ink variant {variant!r}; choose from {", ".join(INK_VARIANTS)}')
    layer = bpy.context.view_layer if bpy.context.scene == scene else None
    if layer is None or not layer.use:
        layer = next((layer for layer in scene.view_layers if layer.use), None)
    if layer is None:
        raise ValueError('Ink needs an enabled view layer')

    if scene.render.engine not in {'BLENDER_EEVEE', 'CYCLES'}:
        scene.render.engine = 'BLENDER_EEVEE'
    layer.use_pass_z = layer.use_pass_normal = True
    tree = bpy.data.node_groups.new(f'SketchBlend Ink · {key}', 'CompositorNodeTree')
    previous = scene.compositing_node_group
    try:
        scene.compositing_node_group = tree
        _build(tree, scene, layer, key)
    except Exception:
        scene.compositing_node_group = previous
        bpy.data.node_groups.remove(tree)
        raise
    scene.render.use_compositing = True
    if key == 'COZY_INK':
        return tree
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    return tree
