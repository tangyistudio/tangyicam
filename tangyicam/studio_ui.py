"""Local production controls. Every visible operation has an executable backend."""
from pathlib import Path
import json
import bpy
from . import studio, agent_bridge, animation_tools

TABS=[(n,l,'') for n,l in [('SCENE','場景'),('MODEL','模型'),('ANIMATION','動畫'),('IMAGE','圖片'),('VIDEO','影片'),('CAMERA','運鏡'),('ASSET','素材')]]
ROLES=[(n,l,'') for n,l in [('STORYBOARD','分鏡／動作'),('SCENE','場景／材質'),('CHARACTER','人物外觀'),('PROP','道具'),('FIRST_FRAME','首幀'),('LAST_FRAME','尾幀')]]

class TC_Reference(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name='英文名稱')
    path: bpy.props.StringProperty(name='檔案',subtype='FILE_PATH')
    element_id: bpy.props.StringProperty(name='Higgsfield Element ID')
    role: bpy.props.EnumProperty(name='用途',items=ROLES,default='SCENE')
    owner: bpy.props.StringProperty(name='所屬角色／物件',default='scene')

class TC_StudioProps(bpy.types.PropertyGroup):
    tab: bpy.props.EnumProperty(items=TABS,default='SCENE')
    recipe: bpy.props.StringProperty(name='建置／骨架／動作 JSON',subtype='FILE_PATH')
    prompt: bpy.props.StringProperty(name='場景描述',default='黑色大理石廁所 / restroom')
    width: bpy.props.FloatProperty(name='寬度 m',default=5,min=2,max=100)
    length: bpy.props.FloatProperty(name='長度 m',default=12,min=3,max=200)
    height: bpy.props.FloatProperty(name='高度 m',default=3,min=2,max=30)
    asset_path: bpy.props.StringProperty(name='素材檔案',subtype='FILE_PATH')
    output: bpy.props.StringProperty(name='輸出資料夾',subtype='DIR_PATH',default='//tc_studio/')
    prompt_text: bpy.props.PointerProperty(name='完整生成提示詞',type=bpy.types.Text)
    image_mode: bpy.props.EnumProperty(name='匯入方式',items=[('PLANE','圖片平面',''),('MATERIAL','指定物件材質','')])
    rig: bpy.props.PointerProperty(name='角色骨架',type=bpy.types.Object,poll=lambda s,o:o.type=='ARMATURE')
    target: bpy.props.PointerProperty(name='IK 接觸目標',type=bpy.types.Object)
    pole: bpy.props.PointerProperty(name='IK 肘／膝方向',type=bpy.types.Object)
    bone: bpy.props.StringProperty(name='末端骨骼名稱')
    refs: bpy.props.CollectionProperty(type=TC_Reference)
    ref_index: bpy.props.IntProperty(default=0)
    message: bpy.props.StringProperty(default='本機功能不消耗 Higgsfield 點數')

class TC_OT_studio(bpy.types.Operator):
    bl_idname='tangyicam.studio'
    bl_label='TangyiCam Studio（實驗）'
    bl_options={'REGISTER','UNDO'}
    command: bpy.props.StringProperty()
    def execute(self,context):
        p=context.scene.tc_studio;s=context.scene
        try:
            cmd=self.command
            if cmd=='room':
                col=studio.build_scene(studio.room_recipe(p.prompt,p.width,p.length,p.height));p.message='已新增可編輯場景：'+col.name
            elif cmd=='recipe':
                col=studio.build_scene(studio.load_json(p.recipe));p.message='已建置：'+col.name
            elif cmd=='import':
                added=studio.import_asset(p.asset_path);p.message=f'已匯入 {len(added)} 個物件'
            elif cmd=='image':
                obj=studio.image_asset(p.asset_path,p.image_mode,context.active_object);p.message='已匯入：'+obj.name
            elif cmd=='rig':
                meshes=[o for o in context.selected_objects if o.type=='MESH']
                p.rig=studio.create_rig(studio.load_json(p.recipe),meshes);p.message='已建立骨架；請檢查權重與關節'
            elif cmd=='import_motion':
                result=animation_tools.import_motion(p.asset_path,p.rig);p.message='已轉入動作：'+result['action']
            elif cmd=='contact':
                result=animation_tools.contact_target(p.rig,p.bone,s.frame_start,s.frame_end);p.message='已固定接觸目標：'+result['target']
            elif cmd=='motion':
                act=studio.apply_motion(p.rig,studio.load_json(p.recipe));p.message='已建立新動作：'+act.name
            elif cmd=='ik':
                if not p.target:raise ValueError('請先選取 IK 目標')
                studio.add_ik(p.rig,p.bone,p.target,p.pole);p.message='已加入不拉伸 IK 接觸約束'
            elif cmd=='camera':
                spec=studio.load_json(p.recipe);cam=studio.camera_path(spec['keys'],spec.get('name','TC_StudioCamera'));p.message='已建立連續相機：'+cam.name
            elif cmd=='flicker':
                if not context.active_object:raise ValueError('先選取燈管物件')
                studio.flicker(context.active_object,s.frame_start,s.frame_end);p.message='已加入單燈發光與照明同步閃爍'
            elif cmd=='fixture':
                obj=studio.fixture('TC_Fixture',s.cursor.location);p.message='已新增：'+obj.name
            elif cmd=='audit':
                result=studio.audit_motion(s,context.selected_objects,s.frame_start,s.frame_end)
                out=Path(bpy.path.abspath(p.output));out.mkdir(parents=True,exist_ok=True)
                (out/'motion_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                p.message=f"位置跳動警示 {len(result['position_jumps'])}；接觸品質仍需看片"
            elif cmd in {'first','last','still'}:
                frame=s.frame_start if cmd=='first' else s.frame_end if cmd=='last' else s.frame_current
                path=Path(bpy.path.abspath(p.output))/(cmd+'.png')
                agent_bridge.render_frame({'path':str(path),'frame':frame});p.message='已輸出：'+str(path)
            elif cmd=='packet':
                if not p.prompt_text:raise ValueError('先選擇完整提示詞 Text 資料')
                refs=[{k:getattr(r,k) for k in ('name','path','element_id','role','owner')} for r in p.refs]
                studio.reference_packet(s,p.output,p.prompt_text.as_string(),refs);p.message='已匯出提示詞與具名素材清單；尚未送出生成'
            elif cmd=='add_ref':
                r=p.refs.add();r.path=p.asset_path;r.name=Path(p.asset_path).stem;p.ref_index=len(p.refs)-1
            elif cmd=='remove_ref':
                if len(p.refs):p.refs.remove(min(p.ref_index,len(p.refs)-1));p.ref_index=max(0,p.ref_index-1)
            elif cmd=='open_folder':
                path=Path(bpy.path.abspath(p.output));path.mkdir(parents=True,exist_ok=True);bpy.ops.wm.path_open(filepath=str(path))
            elif cmd=='agent_start':p.message='本機 Agent 已啟動：'+agent_bridge.start()
            elif cmd=='agent_stop':agent_bridge.stop();p.message='本機 Agent 已停止'
            else:raise ValueError('Unknown operation')
            self.report({'INFO'},p.message);return {'FINISHED'}
        except Exception as exc:
            p.message=str(exc);self.report({'ERROR'},p.message);return {'CANCELLED'}

class TC_UL_refs(bpy.types.UIList):
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        layout.label(text=item.name or '未命名',icon='IMAGE_DATA')
        layout.label(text=dict((x[0],x[1]) for x in ROLES).get(item.role,''))

def button(layout,cmd,label,icon='NONE'):
    op=layout.operator('tangyicam.studio',text=label,icon=icon);op.command=cmd

class TC_PT_studio(bpy.types.Panel):
    bl_label='TangyiCam Studio 0.3'
    bl_idname='TC_PT_studio'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='TangyiCam';bl_order=-10
    def draw(self,context):
        lay=self.layout;p=context.scene.tc_studio
        button(lay,'agent_stop' if agent_bridge.running() else 'agent_start','停止 Agent' if agent_bridge.running() else '啟動本機 Agent','CONSOLE')
        lay.label(text='由目前對話控制 Blender；本機執行')
        lay.prop(p,'tab',expand=True)
        if p.tab=='SCENE':
            lay.prop(p,'prompt');row=lay.row();row.prop(p,'width');row.prop(p,'length');row.prop(p,'height')
            button(lay,'room','建立參數化房間／廁所','MESH_CUBE')
            lay.label(text='此按鈕使用範本；自由文字場景由 Agent 建置')
            lay.prop(p,'recipe');button(lay,'recipe','套用 Agent 場景 JSON','IMPORT')
            button(lay,'fixture','在游標新增實體燈管','LIGHT_AREA');button(lay,'flicker','選取燈管加入物理閃爍','LIGHT')
        elif p.tab=='MODEL':
            lay.prop(p,'asset_path');button(lay,'import','匯入 GLB / FBX / OBJ / BLEND','IMPORT')
            lay.label(text='保留骨架與材質，放到 3D 游標位置')
        elif p.tab=='ANIMATION':
            lay.prop(p,'recipe');button(lay,'rig','依骨架 JSON 綁定選取網格','ARMATURE_DATA')
            lay.prop(p,'rig');lay.prop(p,'asset_path');button(lay,'import_motion','匯入相容 FBX 動作','IMPORT');button(lay,'motion','套用動作 JSON（保留舊 Action）','ACTION')
            lay.prop(p,'bone');lay.prop(p,'target');lay.prop(p,'pole');button(lay,'ik','加入手／腳接觸 IK','CON_KINEMATIC');button(lay,'contact','目前區間固定末端接觸','CONSTRAINT_BONE')
            button(lay,'audit','檢查選取物件的位置跳動','CHECKMARK')
        elif p.tab in {'IMAGE','VIDEO'}:
            lay.prop(p,'output');lay.prop(p,'prompt_text')
            row=lay.row();button(row,'first','輸出首幀');button(row,'last','輸出尾幀')
            if p.tab=='IMAGE':
                button(lay,'still','渲染目前畫面','RENDER_STILL');lay.prop(p,'asset_path');lay.prop(p,'image_mode');button(lay,'image','匯入圖片／影片平面或材質','IMAGE_DATA')
            else:lay.label(text='現有 Take MP4 輸出位於下方手機控制器')
            button(lay,'packet','匯出具名參考＋完整提示詞','EXPORT')
            lay.label(text='生成請送入 Cinema Studio 參賽專案')
        elif p.tab=='CAMERA':
            lay.prop(p,'recipe');button(lay,'camera','建立連續運鏡路徑','CAMERA_DATA');button(lay,'audit','檢查相機位置跳動','CHECKMARK')
            lay.label(text='手機、軌道、慢動作與 Take 控制在下方')
        elif p.tab=='ASSET':
            lay.prop(p,'asset_path');button(lay,'add_ref','加入具名素材','ADD')
            lay.template_list('TC_UL_refs','',p,'refs',p,'ref_index',rows=4)
            if len(p.refs):
                r=p.refs[min(p.ref_index,len(p.refs)-1)]
                for field in ('name','path','element_id','role','owner'):lay.prop(r,field)
                button(lay,'remove_ref','移除清單項目（保留檔案）','REMOVE')
            lay.prop(p,'output');button(lay,'open_folder','開啟輸出資料夾','FILE_FOLDER')
        lay.separator();lay.label(text=p.message[:90])

CLASSES=(TC_Reference,TC_StudioProps,TC_OT_studio,TC_UL_refs,TC_PT_studio)
def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.tc_studio=bpy.props.PointerProperty(type=TC_StudioProps)
def unregister():
    agent_bridge.stop();del bpy.types.Scene.tc_studio
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
