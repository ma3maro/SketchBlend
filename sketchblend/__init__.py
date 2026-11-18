"""SketchBlend: scene-safe illustration presets for Blender."""
import bpy
from .ink import INK_VARIANTS, install_ink

bl_info = {
    'name': 'SketchBlend', 'version': (0, 6, 1), 'blender': (5, 3, 0),
    'category': '3D View', 'location': '3D View > Sidebar > SketchBlend',
}


# name, base color, outline, shadows, cavity, background
PRESETS = {
    'SPRITE': ('Flat Pixel Sprite', None, (.014,.009,.027), False, None, (.02,.03,.075)),
    'PIXEL': ('Pixel Storybook', None, None, True, None, (.12,.17,.22)),
    'PIXEL_DIORAMA': ('Textured Pixel Diorama', None, None, True, None, (0,0,0)),
    'PAINTED': ('Harbor Color', None, None, True, None, (0,0,0)),
    'MEADOW': ('Muted Pastoral Pixel', None, None, True, None, (.44,.49,.41)),
    'CLAY': ('Clay', (.66,.66,.66), None, True, 'BOTH', (.11,.13,.16)),
    'COLOR': ('Color', None, None, True, 'WORLD', (.22,.30,.36)),
    'COLOR_LINE': ('Color + Line', None, (.031,.023,.026), True, 'BOTH', (.22,.30,.36)),
    'LINE_WHITE': ('Line + White', (.97,.95,.89), (.045,.034,.030), False, 'SCREEN', (.89,.86,.79)),
    'BLUEPRINT': ('Blueprint', (.018,.041,.116), (.43,.72,.97), False, None, (.018,.041,.116)),
    'LINES_ONLY': ('Lines Only', (.97,.97,.97), (.009,.009,.009), False, None, (.97,.97,.97)),
    'TONE': ('Tone', (.56,.56,.56), None, True, 'SCREEN', (.82,.82,.82)),
    'LINE_TONE': ('Line + Tone', (.95,.95,.95), (.010,.010,.010), True, 'SCREEN', (.82,.82,.82)),
    'COLOR_TONE': ('Color + Tone', None, None, True, 'SCREEN', (.30,.34,.39)),
    'COLOR_LINE_TONE': ('Color + Line + Tone', None, (.009,.012,.017), True, 'SCREEN', (.30,.34,.39)),

}


PIXEL_PRESETS = ('SPRITE', 'PIXEL', 'MEADOW', 'PIXEL_DIORAMA')

for _key in sorted(INK_VARIANTS):
    PRESETS.setdefault(_key, (_key.replace('_', ' ').title(), None, None, False, None, (0,0,0)))

FEATURED = (
    ('Color & Form', ('COLOR', 'CLAY')),
    ('Drafting & Print', ('LINES_ONLY', 'LINE_TONE', 'BLUEPRINT', 'HALFTONE', 'COMIC_STYLE')),
    ('Graphite', ('SKETCHY_SHADED',)),
    ('Pixel Art', ('PIXEL_DIORAMA', 'MEADOW', 'PIXEL', 'SPRITE')),
    ('Illustration', ('PAINTED', 'COZY_INK')),
)
PRESETS['COZY_INK'] = ('Cozy Ink', None, None, False, None, (0,0,0))


def pixel_graph(scene, block_size, bands, finish='pixel'):
    tree = bpy.data.node_groups.new('SketchBlend Pixel Finish', 'CompositorNodeTree')
    scene.compositing_node_group = tree
    scene.render.use_compositing = True
    tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    layers = tree.nodes.new('CompositorNodeRLayers')
    # Quantize luminance, not channels: individually rounding RGB turns
    # dark teal into blue or black and destroys narrow accent colors.
    luminance = tree.nodes.new('CompositorNodeRGBToBW')
    tree.links.new(layers.outputs['Image'], luminance.inputs[0])

    def math_node(op, left, right, x):
        node = tree.nodes.new('ShaderNodeMath')
        node.operation = op
        node.location = (x, -210)
        for socket, value in zip(node.inputs, (left, right)):
            if isinstance(value, (int, float)):
                socket.default_value = value
            else:
                tree.links.new(value, socket)
        return node.outputs[0]

    luminance.location = (190, -210)
    luma = luminance.outputs[0]
    gamma = math_node('POWER', luma, .45, 390)
    scene['sb_tone_bands'] = bands
    interval = 1 / bands
    steps = math_node('SNAP', gamma, interval, 590)
    # SNAP rounds down; add half a band before snapping to round to nearest.
    bias = math_node('ADD', gamma, interval / 2, 380)
    tree.links.new(bias, steps.node.inputs[0])
    steps.node.name = 'SB Band interval'
    bias.node.name = 'SB Band rounding'
    offset = steps
    linear = math_node('POWER', offset, 1/.45, 990)
    safe = math_node('MAXIMUM', luma, .0001, 990)
    ratio = math_node('DIVIDE', linear, safe, 1190)
    gain = math_node('MINIMUM', ratio, 1.45, 1390)
    shade = tree.nodes.new('ShaderNodeVectorMath')
    shade.operation = 'SCALE'
    shade.location.x = 1590
    tree.links.new(layers.outputs['Image'], shade.inputs[0])
    tree.links.new(gain, shade.inputs['Scale'])
    pixel = tree.nodes.new('CompositorNodePixelate')
    pixel.name = 'SB Pixel grid'
    pixel.inputs['Size'].default_value = block_size
    output = tree.nodes.new('NodeGroupOutput')
    pixel.location.x = 1790
    output.location.x = 1990
    image = shade.outputs['Vector']
    mix = tree.nodes.new('ShaderNodeMixRGB')
    mix.name = 'SB Tone blend'
    mix.inputs[0].default_value = {'harbor': .12, 'pastoral': .75, 'sprite': .78}.get(finish, .52)
    tree.links.new(layers.outputs['Image'], mix.inputs[1])
    tree.links.new(image, mix.inputs[2])
    wash = tree.nodes.new('CompositorNodeHueSat')
    wash.name = 'SB Pixel color'
    wash.inputs['Saturation'].default_value = {'harbor': 1.09, 'pastoral': .59, 'sprite': 1.18}.get(finish, 1.05)
    wash.inputs['Value'].default_value = {'harbor': 1.08, 'pastoral': 1.03}.get(finish, 1)
    graded = mix.outputs[0]
    if finish != 'harbor':
        # Modulate material colors with a separate shadow/highlight palette.
        # This still changes the image with the pixel grid turned off.
        ramp = tree.nodes.new('ShaderNodeValToRGB')
        ramp.name = 'SB Shadow and highlight palette'
        ramp.location = (1740, -460)
        palette = ramp.color_ramp
        palette.interpolation = 'EASE'
        shadow, middle, light = {
            'pastoral': ((.73, .83, .96), (.96, .96, .85), (1, .94, .72)),
            'sprite': ((.62, .77, 1), (.98, .93, .80), (1, .89, .67)),
        }.get(finish, ((.60, .82, 1), (.92, 1, .87), (1, .91, .71)))
        palette.elements[0].position = .17
        palette.elements[0].color = (*shadow, 1)
        palette.elements[1].position = .78
        palette.elements[1].color = (*light, 1)
        palette.elements.new(.46).color = (*middle, 1)
        tree.links.new(gamma, ramp.inputs[0])
        grade = tree.nodes.new('ShaderNodeMixRGB')
        grade.name = 'SB Material palette grade'
        grade.blend_type = 'MULTIPLY'
        grade.inputs[0].default_value = 1
        tree.links.new(graded, grade.inputs[1])
        tree.links.new(ramp.outputs[0], grade.inputs[2])
        graded = grade.outputs[0]
    tree.links.new(graded, wash.inputs['Image'])
    tree.links.new(wash.outputs['Image'], pixel.inputs['Color'])
    finish = tree.nodes.new('ShaderNodeMixRGB')
    finish.name = 'SB Pixel blend'
    finish.inputs[0].default_value = int(block_size > 1)
    tree.links.new(wash.outputs['Image'], finish.inputs[1])
    tree.links.new(pixel.outputs['Color'], finish.inputs[2])
    tree.links.new(finish.outputs[0], output.inputs['Image'])
    for x, node in enumerate((mix, wash, pixel, finish, output), 8):
        node.location.x = 220 * x


def _band_get(scene):
    return scene.get('sb_tone_bands', 11)


def _band_set(scene, value):
    scene['sb_tone_bands'] = value
    tree = scene.compositing_node_group
    if tree and tree.nodes.get('SB Band interval') and tree.nodes.get('SB Band rounding'):
        tree.nodes['SB Band interval'].inputs[1].default_value = 1 / value
        tree.nodes['SB Band rounding'].inputs[1].default_value = .5 / value


_INK_CONTROLS = {
    'ink': ('Ink strength', 'SB Ink strength', 0.0, 2.0),
    'depth': ('Silhouette strength', 'SB Depth strength', 0.0, 2.0),
    'crease': ('Crease strength', 'SB Crease strength', 0.0, 2.0),
    'detail': ('Texture lines', 'SB Detail strength', 0.0, 1.5),
    'screen': ('Dot strength', 'SB Screen strength', 0.0, 2.0),
    'period': ('Dot spacing', 'SB Dot period', 3.0, 30.0),
    'hatch': ('Hatch strength', 'SB Hatch strength', 0.0, 1.5),
}


def _ink_slider(key, name, node_name, low, high):
    def get(scene):
        tree = scene.compositing_node_group
        node = tree.nodes.get(node_name) if tree else None
        return node.inputs[1].default_value if node else low

    def set(scene, value):
        tree = scene.compositing_node_group
        node = tree.nodes.get(node_name) if tree else None
        if node:
            node.inputs[1].default_value = value
        if key == 'period' and tree and tree.nodes.get('SB Dot period V'):
            tree.nodes['SB Dot period V'].inputs[1].default_value = value

    return bpy.props.FloatProperty(name=name, min=low, max=high, get=get, set=set)


def _draw_tuning(layout, scene, preset):
    box = layout.box()
    box.label(text='Tune this scene', icon='PREFERENCES')
    view = scene.view_settings
    box.prop(view, 'exposure', slider=True)
    box.prop(view, 'gamma', slider=True)
    tree = scene.compositing_node_group
    nodes = tree.nodes if tree else {}

    def knob(node, socket, text, slider=True):
        item = nodes.get(node)
        if item:
            box.prop(item.inputs[socket], 'default_value', text=text, slider=slider)

    if preset in (*PIXEL_PRESETS, 'PAINTED') and nodes.get('SB Tone blend'):
        if preset != 'PAINTED':
            knob('SB Pixel grid', 'Size', 'Pixel size', False)
            knob('SB Pixel blend', 0, 'Pixel strength')
        box.prop(scene, 'styleblend_bands', text='Tone bands', slider=True)
        knob('SB Tone blend', 0, 'Tone strength')
        knob('SB Pixel color', 'Saturation', 'Saturation')
        knob('SB Pixel color', 'Value', 'Brightness')
    elif preset in INK_VARIANTS and nodes.get('SB Ink strength'):
        if nodes.get('SB Silhouette width'):
            box.prop(scene, 'styleblend_ink_width')
            box.prop(scene, 'styleblend_crease_width')
        else:
            box.label(text='Reapply to enable ink thickness.')
        for key, (_, node_name, _, _) in _INK_CONTROLS.items():
            if nodes.get(node_name):
                box.prop(scene, f'styleblend_{key}', slider=True)
        knob('SB Material color mix', 0, 'Material color')
        knob('SB Ink color', 2, 'Ink color', False)
    elif scene.render.engine == 'BLENDER_WORKBENCH':
        shading = scene.display.shading
        box.prop(shading, 'light', text='Lighting')
        box.prop(shading, 'color_type', text='Color source')
        if shading.color_type == 'SINGLE':
            box.prop(shading, 'single_color', text='Surface color')
        box.prop(shading, 'show_shadows')
        if shading.show_shadows:
            box.prop(scene.display, 'shadow_focus', slider=True)
        box.prop(shading, 'show_cavity', text='Surface detail')
        if shading.show_cavity:
            box.prop(shading, 'cavity_type')
            if shading.cavity_type in {'SCREEN', 'BOTH'}:
                box.prop(shading, 'curvature_ridge_factor', slider=True)
                box.prop(shading, 'curvature_valley_factor', slider=True)
            if shading.cavity_type in {'WORLD', 'BOTH'}:
                box.prop(shading, 'cavity_ridge_factor', slider=True)
                box.prop(shading, 'cavity_valley_factor', slider=True)
        box.prop(shading, 'show_object_outline', text='Outlines')
        if shading.show_object_outline:
            box.prop(shading, 'object_outline_color', text='Outline color')
    else:
        box.label(text='Reapply this preset to unlock tuning.')


def apply_style(scene, preset, pixel_size=0, bands=11):
    if preset in INK_VARIANTS:
        install_ink(scene, preset)
        return
    if preset in {'PAINTED', 'PIXEL_DIORAMA', 'MEADOW'}:
        if scene.render.engine not in {'BLENDER_EEVEE', 'CYCLES'}:
            scene.render.engine = 'BLENDER_EEVEE'
        params = {'PAINTED': (1, bands, 'harbor'),
                  'PIXEL_DIORAMA': (pixel_size or 2, bands, 'pixel'),
                  'MEADOW': (pixel_size or 3, min(bands, 8), 'pastoral')}
        pixel_graph(scene, *params[preset])
        return
    _, color, outline, shadows, cavity, background = PRESETS[preset]
    scene.render.engine = 'BLENDER_WORKBENCH'
    # Never run the source compositor over a Workbench style.
    scene.render.use_compositing = False
    shading = scene.display.shading
    shading.light = 'FLAT' if preset in {'LINE_WHITE', 'BLUEPRINT', 'LINES_ONLY', 'SPRITE'} else 'STUDIO'
    if preset in {'COLOR', 'COLOR_LINE', 'COLOR_TONE', 'COLOR_LINE_TONE'}:
        shading.studio_light = 'paint.sl'
    shading.color_type = 'MATERIAL' if color is None else 'SINGLE'
    if color is not None:
        shading.single_color = color
    shading.show_shadows = shadows
    scene.display.shadow_shift = .12 if preset.endswith('TONE') else .25
    scene.display.shadow_focus = .79 if preset.endswith('TONE') else .42
    shading.curvature_ridge_factor = 0 if preset in {'LINE_TONE', 'LINE_WHITE'} else .55
    shading.curvature_valley_factor = 1.5 if preset.endswith('TONE') else .65
    shading.show_cavity = cavity is not None
    if cavity:
        shading.cavity_type = cavity
    shading.show_object_outline = outline is not None
    if outline is not None:
        shading.object_outline_color = outline
    shading.background_type = 'WORLD'
    # The Workbench camera render takes its background from the scene World.
    # Give the linked copy its own World instead of mutating the source's.
    scene.world = bpy.data.worlds.new(f'SketchBlend - {preset}')
    scene.world.color = background
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    if preset == 'PIXEL':
        shading.studio_light = 'paint.sl'
        pixel_graph(scene, pixel_size or 5, bands)
    elif preset == 'SPRITE':
        pixel_graph(scene, pixel_size or 7, bands, 'sprite')


class STYLEBLEND_OT_apply(bpy.types.Operator):
    bl_idname = 'styleblend.apply'
    bl_label = 'Apply SketchBlend Preset'
    bl_options = {'REGISTER', 'UNDO'}

    preset: bpy.props.EnumProperty(items=[(key, value[0], '') for key, value in PRESETS.items()])
    pixel_size: bpy.props.IntProperty(name='Pixel size (0 = Auto)', default=0, min=0, max=32)
    bands: bpy.props.IntProperty(name='Brightness bands', default=11, min=3, max=40)

    def draw(self, context):
        self.layout.prop(self, 'preset')
        if self.preset in PIXEL_PRESETS:
            self.layout.prop(self, 'pixel_size')
        if self.preset in (*PIXEL_PRESETS, 'PAINTED'):
            self.layout.prop(self, 'bands')

    @classmethod
    def poll(cls, context):
        return context.window is not None

    def execute(self, context):
        original = context.scene.styleblend_source or context.scene
        if original.camera is None:
            self.report({'ERROR'}, 'Set an active camera on the original scene before applying a preset.')
            return {'CANCELLED'}
        previous = context.scene
        context.window.scene = original
        if bpy.ops.scene.new(type='LINK_COPY') != {'FINISHED'}:
            context.window.scene = previous
            self.report({'ERROR'}, 'Could not create a SketchBlend scene')
            return {'CANCELLED'}
        styled = context.window.scene
        styled.name = f'{original.name} - {PRESETS[self.preset][0]}'
        styled.styleblend_source = original
        styled['styleblend_preset'] = self.preset
        try:
            apply_style(styled, self.preset, self.pixel_size, self.bands)
        except (RuntimeError, TypeError, ValueError) as exc:
            context.window.scene = previous
            self.report({'ERROR'}, f'Style could not be applied: {exc}')
            return {'CANCELLED'}
        return {'FINISHED'}


class STYLEBLEND_OT_original(bpy.types.Operator):
    bl_idname = 'styleblend.original'
    bl_label = 'Return to Original Scene'
    bl_description = 'Switch back without deleting the styled scene'

    @classmethod
    def poll(cls, context):
        return bool(context.window and context.scene.styleblend_source)

    def execute(self, context):
        context.window.scene = context.scene.styleblend_source
        return {'FINISHED'}


class STYLEBLEND_PT_panel(bpy.types.Panel):
    bl_label = 'SketchBlend'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'SketchBlend'

    def draw(self, context):
        layout = self.layout
        current = context.scene.get('styleblend_preset')
        if context.scene.styleblend_source:
            layout.label(text=PRESETS.get(current, ('Styled Scene',))[0], icon='IMAGE_DATA')
            layout.operator('styleblend.original', icon='LOOP_BACK')
            _draw_tuning(layout, context.scene, current)
        for heading, keys in FEATURED:
            box = layout.box()
            box.label(text=heading)
            grid = box.grid_flow(columns=2, align=True)
            for key in keys:
                grid.operator('styleblend.apply', text=PRESETS[key][0], depress=current == key).preset = key
        layout.label(text='Press F12 again after changing ink.')
        if context.scene.styleblend_source:
            layout.label(text='Model edits are shared.', icon='LINKED')


_CLASSES = (STYLEBLEND_OT_apply, STYLEBLEND_OT_original, STYLEBLEND_PT_panel)


def _width_property(kind):
    def socket(scene):
        tree = scene.compositing_node_group
        node = tree.nodes.get(f'SB {kind} width') if tree else None
        return node.inputs['Size'] if node else None

    def get(scene):
        target = socket(scene)
        return int(target.default_value) if target is not None else 0

    def set(scene, value):
        target = socket(scene)
        if target is not None:
            target.default_value = value

    return bpy.props.IntProperty(name=f'{kind} width (+px per side)', min=0, max=6,
                                 description='Add pixels on each side of the native stroke', get=get, set=set)


def register():
    bpy.types.Scene.styleblend_ink_width = _width_property('Silhouette')
    bpy.types.Scene.styleblend_crease_width = _width_property('Crease')
    for key, spec in _INK_CONTROLS.items():
        setattr(bpy.types.Scene, f'styleblend_{key}', _ink_slider(key, *spec))
    bpy.types.Scene.styleblend_bands = bpy.props.IntProperty(min=3, max=64, get=_band_get, set=_band_set)
    bpy.types.Scene.styleblend_source = bpy.props.PointerProperty(type=bpy.types.Scene)
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    del bpy.types.Scene.styleblend_ink_width
    del bpy.types.Scene.styleblend_crease_width
    for key in _INK_CONTROLS:
        delattr(bpy.types.Scene, f'styleblend_{key}')
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.styleblend_source
    del bpy.types.Scene.styleblend_bands
