/**
 * 卷轴工坊（原型 05）。
 *
 * ## 从「整页空态」改成「有真入口的首页」（2026-09-24）
 *
 * 这一页原来是 `ComingSoon`：一条 tab、一句「这一卷还在撰写中」、一个回大厅的按钮。
 * 私有知识库落地后它必须变成**有路可走**的页面 —— 否则 `kb-list` /
 * `kb-source` 这两屏就只能从大厅过来，而「卷轴工坊」这个 tab 本身
 * 仍然是一块写着「以后会有东西」的牌子（红线：交付页面要连入口一起交）。
 *
 * 保留原来那句话：多源输入**确实**还没做完（网页 / 视频本期不做），
 * 所以它说「还在撰写中」仍然是真的。改的只是把它从整页文案降成一张卡，
 * 把下面那块位置让给两个真入口。
 *
 * ## 与原型的一处有意偏离：不再有「回到社团大厅」
 *
 * 原空态给了那颗按钮，因为那时整页只有一个出口。现在它是标签页 ——
 * 底部标签栏随时能切走，再放一颗「回到大厅」是多余的按钮。
 */

import { Text, View } from '@tarojs/components'

import PhoneShell from '../../components/PhoneShell'
import { WORKSHOP_COPY } from '../../constants/copy'
import { useTabPage } from '../../hooks/useTabPage'
import { useAppStore } from '../../store/useAppStore'
import { goPage } from '../../utils/navigation'

import './index.scss'

export default function WorkshopPage() {
  useTabPage('workshop')

  // 私有知识库的总开关（后端经 `GET /health` 下发）。
  // ⚠️ 关掉时**入口与卡片文案一起变**：入口留着就是给用户指一条走不通的路，
  // 而卡片那句「可以把文档收进知识库」在功能关掉的部署里是假话（design D18）。
  const knowledgeBaseEnabled = useAppStore((s) => s.knowledgeBaseEnabled)

  return (
    <PhoneShell navTitle='卷轴工坊' showBack={false} reserveTabBar>
      <View className='card'>
        <View className='h sm'>{WORKSHOP_COPY.title}</View>
        <View className='sub workshop__desc'>
          {knowledgeBaseEnabled ? WORKSHOP_COPY.descWithKb : WORKSHOP_COPY.descWithoutKb}
        </View>
      </View>

      {knowledgeBaseEnabled && (
        <>
          <View className='li' onClick={() => goPage('/pages/workshop/kb-list/index', 'navigate')}>
            <View className='ico'>
              <Text className='workshop__mark'>库</Text>
            </View>
            <View className='tx'>
              <View className='n'>我的知识库</View>
              <View className='d'>上传过的文档都在这里，可以拿它们出题</View>
            </View>
            <Text className='tiny'>›</Text>
          </View>

          <View className='li' onClick={() => goPage('/pages/workshop/kb-source/index', 'navigate')}>
            <View className='ico'>
              <Text className='workshop__mark'>文</Text>
            </View>
            <View className='tx'>
              <View className='n'>选择输入方式</View>
              <View className='d'>一句话 / 文档 / 网页 / 视频，四种来源各是什么现状</View>
            </View>
            <Text className='tiny'>›</Text>
          </View>
        </>
      )}

      <View className='spacer' />
    </PhoneShell>
  )
}
