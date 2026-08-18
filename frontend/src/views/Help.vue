<template>
  <div>
    <div class="page-head">
      <div>
        <h1>使用帮助</h1>
        <p>报销助手 · 材料齐套、归类、拼版、公文表、记账与物资</p>
      </div>
    </div>

    <div class="help-page card">
      <section class="help-section">
        <h4>整体流程</h4>
        <ol>
          <li>在「条目」或通过批量上传整理报销材料（发票 PDF、订单/支付截图等）。</li>
          <li>把材料放进对应槽位，直到条目显示齐套。</li>
          <li>需要时把条目归入「分组」，填写学生活动预决算等公文表。</li>
          <li>导出：单条拼版、批量拼版，或「导出本组」（可前置填好的表格 PDF）。需要时把条目「记入账本」做经费统计。</li>
        </ol>
      </section>

      <section class="help-section">
        <h4>条目与材料</h4>
        <ul>
          <li><strong>条目</strong>：一笔报销对应一个条目，可查看缺项与齐套状态。</li>
          <li><strong>槽位</strong>：在设置里配置（发票一般为 PDF；其它多为图片）。必填槽未放满则无法导出。</li>
          <li><strong>收件箱</strong>：尚未归入条目的文件暂存处，可再分配。</li>
        </ul>
      </section>

      <section class="help-section">
        <h4>批量上传与自动归类</h4>
        <ul>
          <li>在条目页打开批量上传，一次放入多份材料。</li>
          <li>程序会结合 PDF 文本与 OCR（图片）抽取金额等信息，按规则归入拟建条目，审阅后再入库。</li>
          <li>分类关键词可在「设置 → 分类关键词」中调整，用于按文件名/正文匹配槽位。</li>
        </ul>
      </section>

      <section class="help-section">
        <h4>拼版导出</h4>
        <ul>
          <li>齐套后可导出 A4 纵向 PDF：版式在「设置 → 拼版」中拖拽调整。</li>
          <li>同一槽位可在画板上摆多次；必填槽未放入时无法导出。</li>
          <li>支持单条、多选批量、以及按分组导出。</li>
        </ul>
      </section>

      <section class="help-section">
        <h4>分组与公文表</h4>
        <ul>
          <li>将相关条目放进同一分组后，可「填表」（如学生活动预决算表）。</li>
          <li>表头手填；支出金额按条目归类自动汇总，不可手改金额。</li>
          <li><strong>保存并下载 Word</strong>：生成填好的官方 Word，不依赖本机是否安装 Word。</li>
          <li><strong>预览 PDF / 导出本组前置表格</strong>：需本机安装 Microsoft Word、WPS 或 LibreOffice 之一；内容未改再预览会使用缓存，通常更快。</li>
          <li>表格字段与 Word 模板可在「设置 → 表格」中维护。</li>
        </ul>
      </section>

      <section class="help-section">
        <h4>记账与经费规划</h4>
        <ul>
          <li>侧栏「记账」是独立账本：<strong>收入手记</strong>（拨款、赞助、会费等）；支出可手记，也可从报销条目<strong>一键入账</strong>。</li>
          <li>齐套或导出不会自动入账。同一条目只能入账一次。入账后改条目的金额、标题、分组或填表归类，账本会同步，以保持一致。</li>
          <li>三个视图看同一套流水：<strong>全社团</strong>（收入−支出=余额）、<strong>分活动</strong>（按分组花费，可填活动预算看剩余）、<strong>按科目</strong>（与预决算支出行对齐）。</li>
          <li>科目可在记账页或「设置 → 记账科目」中增删改。</li>
        </ul>
      </section>

      <section class="help-section">
        <h4>物资造册</h4>
        <ul>
          <li>侧栏「物资」用于社团物品台账，与报销条目、拼版分开。</li>
          <li><strong>耐用品</strong>：登记后可借出（填写借用人）和归还；未还清不能删除。</li>
          <li><strong>消耗品</strong>：用入库 / 领用改库存数量。</li>
          <li>登记时可选用关联某条报销（采购来源），不会自动改账本。</li>
          <li><strong>图书</strong>请继续用你们现有的 CSV 表格管理，本程序不做图书编目。</li>
        </ul>
      </section>

      <section class="help-section">
        <h4>外观与其它</h4>
        <ul>
          <li>「设置 → 外观」可切换预设主题，仅影响本机界面。</li>
          <li>数据保存在本机 <code>data/</code>（上传、导出、数据库）；日志见 <code>data/logs/</code>。换电脑或 U 盘交接请用「设置 → 数据」下载/恢复备份（不含主题和拼版缓存）。</li>
          <li>软件只监听本机地址，不主动访问外网。若安全软件误报，可将安装/解压目录加入信任区。</li>
        </ul>
      </section>
    </div>
  </div>
</template>
